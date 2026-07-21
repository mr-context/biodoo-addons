from odoo import fields, models


class HrRequestType(models.Model):
    _name = 'hr.request.type'
    _description = 'Type de demande RH'
    _order = 'sequence, id'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code', required=True)  # MISSION / SORTIE / CONGE
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    icon = fields.Char(string='Icône Bootstrap', default='bi-file-earmark-text')
    color = fields.Integer(string='Couleur', default=0)

    team_id = fields.Many2one(
        'assistance.team',
        string='Équipe traitante',
        ondelete='set null',
        help='Équipe assistance chargée de traiter ces demandes',
    )
    requires_dates = fields.Boolean(
        string='Dates requises',
        default=False,
        help='Affiche les champs Date début / Date fin sur le formulaire portail',
    )
    requires_justification = fields.Boolean(
        string='Justification requise',
        default=False,
    )
    creates_hr_leave = fields.Boolean(
        string="Crée un congé à l'approbation",
        default=False,
        help="Si activé, crée automatiquement un hr.leave quand le ticket est résolu",
    )
    leave_type_id = fields.Many2one(
        'hr.leave.type',
        string='Type de congé',
        help="Type de congé à créer si creates_hr_leave=True",
    )
