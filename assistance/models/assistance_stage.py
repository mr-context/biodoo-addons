from odoo import fields, models


class AssistanceStage(models.Model):
    _name = 'assistance.stage'
    _description = 'Étape de ticket d\'assistance'
    _order = 'sequence, id'

    name = fields.Char(string='Nom', required=True, translate=True)
    sequence = fields.Integer(string='Séquence', default=10)
    team_ids = fields.Many2many(
        'assistance.team',
        'assistance_stage_team_rel',
        'stage_id', 'team_id',
        string='Équipes',
        help='Étape visible pour ces équipes. Laissez vide pour toutes les équipes.',
    )
    fold = fields.Boolean(
        string='Replié',
        default=False,
        help='Colonne repliée par défaut dans la vue Kanban.',
    )
    is_closed = fields.Boolean(
        string='Étape fermée',
        default=False,
        help='Les tickets dans cette étape sont considérés comme résolus.',
    )
    active = fields.Boolean(default=True)
