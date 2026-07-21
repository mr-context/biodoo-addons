import logging
from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrLoan(models.Model):
    _name = 'hr.loan'
    _description = 'Prêt salarial'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc, id desc'

    name = fields.Char(
        string='Référence',
        readonly=True,
        copy=False,
        default=lambda self: _('Nouveau'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employé',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    amount = fields.Float(
        string='Montant total',
        required=True,
        tracking=True,
    )
    nb_months = fields.Integer(
        string='Nombre de mensualités',
        required=True,
        default=6,
        tracking=True,
    )
    amount_per_month = fields.Float(
        string='Mensualité estimée',
        compute='_compute_amount_per_month',
    )
    date_request = fields.Date(
        string='Date de demande',
        default=fields.Date.today,
        required=True,
    )
    date_approval = fields.Date(
        string="Date d'approbation",
        readonly=True,
        tracking=True,
    )
    state = fields.Selection([
        ('draft',        'Brouillon'),
        ('pending_sign', 'En attente de signature'),
        ('approved',     'Approuvé'),
        ('ongoing',      'En cours'),
        ('closed',       'Clôturé'),
        ('refused',      'Refusé'),
    ], default='draft', string='État', tracking=True, copy=False)

    # Champs signature engagement
    commitment_signed = fields.Boolean(
        string='Engagement signé par l\'employé',
        tracking=True,
    )
    bank_check_signed = fields.Boolean(
        string='Chèque de banque signé',
        tracking=True,
    )
    bank_check_number = fields.Char(
        string='N° du chèque de banque',
    )
    commitment_date = fields.Date(
        string='Date de signature',
    )

    reason = fields.Text(string='Motif')
    ticket_id = fields.Many2one(
        'assistance.ticket',
        string='Demande portail',
        readonly=True,
        copy=False,
    )
    loan_line_ids = fields.One2many(
        'hr.loan.line',
        'loan_id',
        string='Échéancier',
        copy=False,
    )
    amount_paid = fields.Float(
        string='Total remboursé',
        compute='_compute_amounts',
        store=True,
    )
    amount_remaining = fields.Float(
        string='Reste à rembourser',
        compute='_compute_amounts',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    # ------------------------------------------------------------------

    @api.depends('amount', 'nb_months')
    def _compute_amount_per_month(self):
        for loan in self:
            if loan.nb_months > 0:
                loan.amount_per_month = round(loan.amount / loan.nb_months, 2)
            else:
                loan.amount_per_month = 0.0

    @api.depends('loan_line_ids.paid', 'loan_line_ids.amount')
    def _compute_amounts(self):
        for loan in self:
            paid = sum(l.amount for l in loan.loan_line_ids if l.paid)
            loan.amount_paid = paid
            loan.amount_remaining = loan.amount - paid

    @api.constrains('amount')
    def _check_amount(self):
        for loan in self:
            if loan.amount <= 0:
                raise ValidationError(_('Le montant du prêt doit être positif.'))

    @api.constrains('nb_months')
    def _check_nb_months(self):
        for loan in self:
            if loan.nb_months <= 0:
                raise ValidationError(_('Le nombre de mensualités doit être supérieur à 0.'))

    # ------------------------------------------------------------------
    # Actions workflow
    # ------------------------------------------------------------------

    def action_request_sign(self):
        """Imprime l'engagement et passe en attente de signature."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Seul un prêt en brouillon peut être mis en attente de signature.'))
        self.write({'state': 'pending_sign'})
        self.message_post(
            body=Markup('Bon d\'engagement imprimé par <b>%s</b>. En attente des signatures.')
            % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )
        return self.env.ref('hr_dz_loan.action_report_loan_commitment').report_action(self)

    def action_approve(self):
        """RH approuve le prêt après vérification des signatures."""
        self.ensure_one()
        if self.state != 'pending_sign':
            raise UserError(_('Le prêt doit être en attente de signature avant approbation.'))
        if not self.commitment_signed:
            raise UserError(_('Veuillez confirmer que l\'employé a signé l\'engagement.'))
        if not self.bank_check_signed:
            raise UserError(_('Veuillez confirmer que le chèque de banque a été signé.'))
        seq = self.env['ir.sequence'].next_by_code('hr.loan') or '/'
        self.write({
            'name': seq,
            'state': 'approved',
            'date_approval': fields.Date.today(),
        })
        self._generate_loan_lines()
        self.message_post(
            body=Markup('Prêt <b>%(ref)s</b> approuvé par <b>%(user)s</b>. Échéancier généré.')
            % {'ref': escape(self.name), 'user': escape(self.env.user.name)},
            subtype_xmlid='mail.mt_comment',
        )

    def action_refuse(self):
        """RH refuse le prêt."""
        self.ensure_one()
        self.write({'state': 'refused'})
        self.message_post(
            body=Markup('Prêt refusé par <b>%s</b>.') % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )

    def action_reset_draft(self):
        self.ensure_one()
        self.loan_line_ids.unlink()
        self.write({
            'state': 'draft',
            'name': _('Nouveau'),
            'date_approval': False,
            'commitment_signed': False,
            'bank_check_signed': False,
            'bank_check_number': False,
            'commitment_date': False,
        })

    def _check_close(self):
        """Clôture automatique si tout est remboursé."""
        for loan in self:
            if loan.state == 'ongoing' and loan.amount_remaining <= 0:
                loan.write({'state': 'closed'})
                loan.message_post(
                    body=Markup('Prêt <b>%s</b> entièrement remboursé — clôturé.') % escape(loan.name),
                    subtype_xmlid='mail.mt_comment',
                )

    # ------------------------------------------------------------------
    # Génération et recalcul de l'échéancier
    # ------------------------------------------------------------------

    def _generate_loan_lines(self):
        """Génère les mensualités à partir du mois suivant l'approbation."""
        self.ensure_one()
        self.loan_line_ids.filtered(lambda l: not l.paid).unlink()
        base = self.date_approval or fields.Date.today()
        monthly = round(self.amount / self.nb_months, 2)
        # Correction arrondi sur la dernière mensualité
        total_rounded = round(monthly * (self.nb_months - 1), 2)
        lines = []
        for i in range(self.nb_months):
            due_date = (base + relativedelta(months=i + 1)).replace(day=1)
            amt = monthly if i < self.nb_months - 1 else round(self.amount - total_rounded, 2)
            lines.append({
                'loan_id': self.id,
                'date': due_date,
                'amount': amt,
                'paid': False,
            })
        self.env['hr.loan.line'].create(lines)
        if self.state == 'approved':
            self.state = 'ongoing'

    def action_recompute_schedule(self):
        """Recalcule les mensualités futures sans toucher aux lignes déjà payées."""
        self.ensure_one()
        paid_lines = self.loan_line_ids.filtered(lambda l: l.paid)
        amount_already_paid = sum(paid_lines.mapped('amount'))
        remaining = self.amount - amount_already_paid
        if remaining <= 0:
            self._check_close()
            return
        # Supprimer les lignes non payées
        self.loan_line_ids.filtered(lambda l: not l.paid).unlink()
        # Recalculer sur les mois restants
        unpaid_count = self.nb_months - len(paid_lines)
        if unpaid_count <= 0:
            # Ajouter une mensualité supplémentaire
            unpaid_count = 1
        monthly = round(remaining / unpaid_count, 2)
        # Base = dernier paiement ou aujourd'hui
        last_paid = paid_lines.sorted('date')[-1].date if paid_lines else fields.Date.today()
        lines = []
        total_new = round(monthly * (unpaid_count - 1), 2)
        for i in range(unpaid_count):
            due_date = (last_paid + relativedelta(months=i + 1)).replace(day=1)
            amt = monthly if i < unpaid_count - 1 else round(remaining - total_new, 2)
            lines.append({
                'loan_id': self.id,
                'date': due_date,
                'amount': amt,
                'paid': False,
            })
        self.env['hr.loan.line'].create(lines)
        self.message_post(
            body=Markup('Échéancier recalculé : <b>%d</b> mensualités restantes.') % unpaid_count,
            subtype_xmlid='mail.mt_note',
        )

    def action_add_month(self):
        """Ajoute une mensualité supplémentaire et recalcule."""
        self.ensure_one()
        self.nb_months += 1
        self.action_recompute_schedule()

    def get_commitment_schedule_preview(self):
        """Retourne l'échéancier prévisionnel pour le bon d'engagement (sans créer de lignes)."""
        self.ensure_one()
        from dateutil.relativedelta import relativedelta as _rd
        base = fields.Date.today()
        monthly = round(self.amount / self.nb_months, 2) if self.nb_months else 0
        total_rounded = round(monthly * (self.nb_months - 1), 2)
        lines = []
        for i in range(self.nb_months):
            due_date = (base + _rd(months=i + 1)).replace(day=1)
            amt = monthly if i < self.nb_months - 1 else round(self.amount - total_rounded, 2)
            lines.append({'index': i + 1, 'date': due_date, 'amount': amt})
        return lines


class HrLoanLine(models.Model):
    _name = 'hr.loan.line'
    _description = 'Mensualité de prêt'
    _order = 'date asc'

    loan_id = fields.Many2one(
        'hr.loan',
        string='Prêt',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        related='loan_id.employee_id',
        store=True,
        string='Employé',
    )
    date = fields.Date(string='Date prévue', required=True)
    amount = fields.Float(string='Montant', required=True)
    paid = fields.Boolean(string='Remboursé', default=False)
    date_paid = fields.Date(string='Date de paiement')
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Bulletin de paie',
        readonly=True,
        copy=False,
    )

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_('Le montant de la mensualité doit être positif.'))

    def action_mark_paid(self):
        """Marquer manuellement une mensualité comme payée (hors bulletin)."""
        for line in self.filtered(lambda l: not l.paid):
            line.write({
                'paid': True,
                'date_paid': fields.Date.today(),
            })
            line.loan_id._check_close()
