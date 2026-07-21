from odoo import fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    dz_leave_accrual_rate = fields.Selection([
        ('2.5', '2.5 jours/mois (légal — 30j/an)'),
        ('1.5', '1.5 jours/mois (18j/an)'),
    ], string='Taux congé annuel', default='2.5',
       help="Taux d'accumulation du congé annuel selon loi 90-11 art. 26")
