from odoo import fields, models


class AssistanceTeam(models.Model):
    _name = 'assistance.team'
    _description = 'Équipe d\'assistance'
    _order = 'name'

    name = fields.Char(string='Nom', required=True, translate=True)
    description = fields.Char(string='Description', translate=True)
    manager_ids = fields.Many2many(
        'res.users',
        'assistance_team_manager_rel',
        'team_id', 'user_id',
        string='Responsables assignation',
        domain="[('share', '=', False)]",
        help='Ces utilisateurs reçoivent un To-Do à chaque nouveau ticket portail '
             'et sont chargés d\'assigner le ticket à un agent.',
    )
    member_ids = fields.Many2many(
        'res.users',
        'assistance_team_users_rel',
        'team_id', 'user_id',
        string='Membres',
        domain="[('share', '=', False)]",
    )
    privacy_visibility = fields.Selection(
        [
            ('invited_internal', 'Privé — membres uniquement'),
            ('internal', 'Tous les employés'),
            ('portal', 'Portail activé — employés + portail'),
        ],
        string='Visibilité',
        required=True,
        default='invited_internal',
        help=(
            "• Privé : seuls les membres de l'équipe voient les tickets.\n"
            "• Tous les employés : tous les utilisateurs internes voient les tickets.\n"
            "• Portail activé : les utilisateurs portail peuvent soumettre des demandes "
            "et tous les employés voient les tickets."
        ),
    )
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Couleur', default=0)
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
    )
    stage_ids = fields.Many2many(
        'assistance.stage',
        'assistance_stage_team_rel',
        'team_id', 'stage_id',
        string='Étapes',
    )

    def _get_first_stage(self):
        """Retourne la première étape (séquence la plus basse) de cette équipe."""
        self.ensure_one()
        return self.env['assistance.stage'].search(
            ['|', ('team_ids', 'in', self.ids), ('team_ids', '=', False)],
            order='sequence, id',
            limit=1,
        )
