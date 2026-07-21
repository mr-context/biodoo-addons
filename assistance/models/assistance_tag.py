from odoo import fields, models


class AssistanceTag(models.Model):
    _name = 'assistance.tag'
    _description = 'Étiquette de ticket d\'assistance'
    _order = 'name'

    name = fields.Char(string='Nom', required=True, translate=True)
    color = fields.Integer(string='Couleur', default=0)
