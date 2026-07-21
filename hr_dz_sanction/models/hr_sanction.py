"""
Procédures disciplinaires — Loi algérienne 90-11 Art.73 (4 degrés).

Workflow :
  draft → convoque → audition → decide → notifie → done
                                                 ↘ cancel (depuis tout état sauf done)

Portail :
  L'employé suit l'avancement, soumet sa réponse d'audition et télécharge les PDFs.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrSanctionType(models.Model):
    """Types de sanction — 4 degrés Loi 90-11 Art.73."""
    _name = 'hr.sanction.type'
    _description = 'Type de sanction disciplinaire'
    _order = 'degree, sequence, id'

    name = fields.Char('Sanction', required=True, translate=True)
    degree = fields.Selection([
        ('1', '1er degré'),
        ('2', '2ème degré'),
        ('3', '3ème degré'),
        ('4', '4ème degré'),
    ], string='Degré', required=True, default='1')
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)


class HrSanctionFault(models.Model):
    """Types de faute professionnelle — liés aux degrés de sanction."""
    _name = 'hr.sanction.fault'
    _description = 'Type de faute professionnelle'
    _order = 'degree, sequence, id'

    name = fields.Char('Faute', required=True, translate=True)
    degree = fields.Selection([
        ('1', '1er degré'),
        ('2', '2ème degré'),
        ('3', '3ème degré'),
        ('4', '4ème degré'),
    ], string='Degré', required=True, default='1')
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)


class HrSanction(models.Model):
    """Dossier disciplinaire complet (convocation + audition + décision)."""
    _name = 'hr.sanction'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'Procédure disciplinaire'
    _order = 'date_incident desc, id desc'
    _rec_name = 'name'

    # ── Identité ──────────────────────────────────────────────────────
    name = fields.Char(
        'Référence', default='/', readonly=True, copy=False, tracking=True,
        help='Généré automatiquement à la décision (ex: 2026/00001)',
    )
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda s: s.env.company, readonly=True, index=True,
    )
    user_id = fields.Many2one(
        'res.users', 'Établi par',
        default=lambda s: s.env.user, readonly=True,
    )
    state = fields.Selection([
        ('draft',    'Nouveau'),
        ('convoque', 'Convoqué'),
        ('audition', 'En audition'),
        ('decide',   'Décision rendue'),
        ('notifie',  'Notifié'),
        ('done',     'Terminé'),
        ('cancel',   'Annulé'),
    ], string='État', default='draft', tracking=True, copy=False)

    # ── Employé ───────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', 'Employé', required=True, tracking=True,
        check_company=True,
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', string='Poste', readonly=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Département', readonly=True,
    )

    # ── Faute / Incident ──────────────────────────────────────────────
    date_incident = fields.Date(
        'Date de l\'incident', required=True, tracking=True,
    )
    fault_id = fields.Many2one(
        'hr.sanction.fault', 'Type de faute', required=True, tracking=True,
    )
    degree = fields.Selection(
        related='fault_id.degree', string='Degré', store=True, readonly=True,
    )
    incident_description = fields.Text(
        'Description de l\'incident', required=True,
    )

    # ── Convocation ───────────────────────────────────────────────────
    date_convocation = fields.Date('Date de convocation', tracking=True)
    audition_date_planned = fields.Date('Date d\'audition prévue')
    convocation_note = fields.Text('Objet / Motif de la convocation')

    # ── Audition (PV) ─────────────────────────────────────────────────
    date_audition = fields.Date('Date d\'audition réelle', tracking=True)
    employee_response = fields.Text('Déclaration de l\'employé')
    audition_observations = fields.Text('Observations de la commission')

    # ── Décision ──────────────────────────────────────────────────────
    sanction_type_id = fields.Many2one(
        'hr.sanction.type', 'Type de sanction',
        domain="[('degree', '=', degree)]",
        tracking=True,
    )
    date_decision = fields.Date('Date de la décision', tracking=True)
    date_effet = fields.Date('Date de prise d\'effet')
    decision_note = fields.Text('Motifs de la décision')

    # ── Notification ──────────────────────────────────────────────────
    date_notification = fields.Date('Date de notification', tracking=True)

    # ── Portail — suivi lecture ────────────────────────────────────────
    portal_read = fields.Boolean(
        'Lu sur le portail',
        default=True, copy=False,
        help='Remis à False à chaque étape clé. '
             'Repassé à True quand l\'employé consulte le dossier depuis le portail.',
    )

    # ── Portal mixin ──────────────────────────────────────────────────
    def _compute_access_url(self):
        super()._compute_access_url()
        for record in self:
            record.access_url = '/my/sanctions/%s' % record.id

    # ── Auto-abonnement de l'employé au chatter ───────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.employee_id.user_id:
                record.message_subscribe(
                    partner_ids=[record.employee_id.user_id.partner_id.id]
                )
        return records

    # ── Workflow ──────────────────────────────────────────────────────

    def action_convoquer(self):
        """Envoyer la convocation à l'audition."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Action non autorisée dans l\'état actuel.'))
            if not rec.date_convocation:
                raise UserError(_('Veuillez renseigner la date de convocation.'))
            rec.state = 'convoque'
            rec.portal_read = False
            body = _(
                'Convocation envoyée le %(conv)s. '
                'Audition prévue le %(audit)s.'
            ) % {
                'conv': rec.date_convocation,
                'audit': rec.audition_date_planned or _('date à préciser'),
            }
            rec.message_post(body=body, subtype_xmlid='mail.mt_comment')

    def action_audition(self):
        """Ouvrir la phase d'audition (PV)."""
        for rec in self:
            if rec.state != 'convoque':
                raise UserError(_('Action non autorisée dans l\'état actuel.'))
            if not rec.date_audition:
                rec.date_audition = fields.Date.today()
            rec.state = 'audition'
            rec.portal_read = False
            rec.message_post(
                body=_('Audition ouverte le %s.') % rec.date_audition,
                subtype_xmlid='mail.mt_note',
            )

    def action_decider(self):
        """Rendre la décision de sanction et générer la référence."""
        for rec in self:
            if rec.state != 'audition':
                raise UserError(_('Action non autorisée dans l\'état actuel.'))
            if not rec.sanction_type_id:
                raise UserError(_(
                    'Veuillez choisir le type de sanction avant de rendre la décision.'
                ))
            if not rec.date_decision:
                raise UserError(_('Veuillez renseigner la date de la décision.'))
            if rec.name == '/':
                rec.name = (
                    self.env['ir.sequence'].next_by_code('hr.sanction') or '/'
                )
            rec.state = 'decide'
            rec.portal_read = False
            rec.message_post(
                body=_(
                    'Décision rendue : <b>%(sanction)s</b> (%(degree)s). '
                    'Date d\'effet : %(effet)s.'
                ) % {
                    'sanction': rec.sanction_type_id.name,
                    'degree': dict(
                        rec.sanction_type_id._fields['degree'].selection
                    ).get(rec.degree, '?'),
                    'effet': rec.date_effet or _('non précisée'),
                },
                subtype_xmlid='mail.mt_comment',
            )

    def action_notifier(self):
        """Notifier l'employé de la décision."""
        for rec in self:
            if rec.state != 'decide':
                raise UserError(_('Action non autorisée dans l\'état actuel.'))
            if not rec.date_notification:
                raise UserError(_('Veuillez renseigner la date de notification.'))
            rec.state = 'notifie'
            rec.portal_read = False
            rec.message_post(
                body=_(
                    'Décision notifiée à l\'employé le %s.'
                ) % rec.date_notification,
                subtype_xmlid='mail.mt_comment',
            )

    def action_done(self):
        """Clôturer la procédure."""
        for rec in self:
            if rec.state != 'notifie':
                raise UserError(_('Action non autorisée dans l\'état actuel.'))
            rec.state = 'done'

    def action_cancel(self):
        """Annuler la procédure."""
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'Impossible d\'annuler une procédure clôturée.'
                ))
            rec.state = 'cancel'

    def action_reset_draft(self):
        """Réinitialiser en brouillon (depuis annulé)."""
        for rec in self:
            if rec.state != 'cancel':
                raise UserError(_(
                    'Seules les procédures annulées peuvent être réinitialisées.'
                ))
            rec.state = 'draft'
            rec.name = '/'

    def unlink(self):
        if any(rec.state not in ('draft', 'cancel') for rec in self):
            raise UserError(_(
                'Suppression non autorisée.\n'
                'Seuls les dossiers en brouillon ou annulés peuvent être supprimés.'
            ))
        return super().unlink()

    # ── Impression ────────────────────────────────────────────────────

    def action_print_convocation(self):
        self.ensure_one()
        return self.env.ref(
            'hr_dz_sanction.report_action_convocation'
        ).report_action(self)

    def action_print_decision(self):
        self.ensure_one()
        if self.state not in ('decide', 'notifie', 'done'):
            raise UserError(_(
                'La décision n\'est pas encore rendue.'
            ))
        return self.env.ref(
            'hr_dz_sanction.report_action_decision'
        ).report_action(self)
