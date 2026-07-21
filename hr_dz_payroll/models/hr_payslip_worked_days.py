"""
Extension de hr.payslip.worked_days pour stocker le lien vers
hr.work.entry.type — nécessaire pour les règles salariales dynamiques
(détection is_paid / is_standard_work sans codes hardcodés).
"""

from odoo import models, fields


class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    work_entry_type_id = fields.Many2one(
        'hr.work.entry.type',
        string='Type de prestation',
        ondelete='set null',
        help='Type de prestation à l\'origine de cette ligne. '
             'Utilisé dans les règles salariales pour détecter '
             'dynamiquement les jours payés (is_paid) et les jours '
             'de présence physique (is_standard_work).',
    )
