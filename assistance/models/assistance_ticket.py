from odoo import api, fields, models


class AssistanceTicket(models.Model):
    _name = 'assistance.ticket'
    _description = 'Ticket d\'assistance'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, id desc'

    # ------------------------------------------------------------------
    # Champs principaux
    # ------------------------------------------------------------------
    ticket_ref = fields.Char(
        string='Référence',
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('assistance.ticket') or '/',
    )
    name = fields.Char(
        string='Sujet',
        required=True,
        tracking=True,
    )
    description = fields.Html(string='Description')

    team_id = fields.Many2one(
        'assistance.team',
        string='Équipe',
        tracking=True,
        ondelete='set null',
    )
    stage_id = fields.Many2one(
        'assistance.stage',
        string='Étape',
        tracking=True,
        group_expand='_read_group_stage_ids',
        ondelete='set null',
        copy=False,
    )
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Urgent')],
        string='Priorité',
        default='0',
        tracking=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Assigné à',
        tracking=True,
        domain="[('share', '=', False)]",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        tracking=True,
    )
    tag_ids = fields.Many2many(
        'assistance.tag',
        string='Étiquettes',
    )
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Couleur', default=0)
    close_date = fields.Datetime(
        string='Date de clôture',
        readonly=True,
        copy=False,
    )
    closed_by_partner = fields.Boolean(
        string='Fermé par le portail',
        readonly=True,
        copy=False,
    )
    kanban_state = fields.Selection(
        [
            ('normal', 'En cours'),
            ('done', 'Prêt pour la prochaine étape'),
            ('blocked', 'Bloqué'),
        ],
        string='État Kanban',
        default='normal',
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        related='team_id.company_id',
        store=True,
    )

    # ------------------------------------------------------------------
    # Group-expand (colonnes Kanban)
    # ------------------------------------------------------------------

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([], order='sequence, id')

    # ------------------------------------------------------------------
    # portal.mixin
    # ------------------------------------------------------------------

    def _compute_access_url(self):
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/assistance/%s' % ticket.id

    # ------------------------------------------------------------------
    # Override write — fermeture automatique
    # ------------------------------------------------------------------

    def write(self, vals):
        # Capture l'ancien user_id avant l'écriture
        old_user = {t.id: t.user_id for t in self} if 'user_id' in vals else {}

        res = super().write(vals)

        # Fermeture automatique lors du changement d'étape
        if 'stage_id' in vals:
            for ticket in self:
                if ticket.stage_id.is_closed and not ticket.close_date:
                    ticket.close_date = fields.Datetime.now()
                elif not ticket.stage_id.is_closed:
                    ticket.close_date = False

        # Création d'un To-Do pour la personne nouvellement assignée
        if 'user_id' in vals and vals['user_id']:
            todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if todo_type:
                for ticket in self:
                    new_user = ticket.user_id
                    prev_user = old_user.get(ticket.id)
                    # Créer seulement si l'assigné a changé
                    if new_user and new_user != prev_user:
                        ticket.activity_schedule(
                            activity_type_id=todo_type.id,
                            summary='Traiter le ticket : %s' % ticket.name,
                            note='<p>Le ticket <b>%s</b> vous a été assigné.</p>'
                                 '<p>Sujet : %s</p>' % (ticket.ticket_ref, ticket.name),
                            user_id=new_user.id,
                        )
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_mark_resolved(self):
        """Passe le ticket à la première étape fermée disponible."""
        closed_stage = self.env['assistance.stage'].search(
            [('is_closed', '=', True)],
            order='sequence, id',
            limit=1,
        )
        if closed_stage:
            self.write({'stage_id': closed_stage.id})

