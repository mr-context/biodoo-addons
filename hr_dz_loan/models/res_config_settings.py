from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    loan_max_amount = fields.Float(
        string='Montant maximum autorisé (DA)',
        help='Informatif — affiché au portail comme plafond recommandé.',
        config_parameter='hr_dz_loan.max_amount',
    )
    loan_max_active = fields.Integer(
        string='Nombre de prêts actifs simultanés',
        help='Nombre maximum de prêts en cours par employé.',
        config_parameter='hr_dz_loan.max_active_loans',
        default=1,
    )
    loan_amount_presets = fields.Char(
        string='Montants suggérés (séparés par des virgules)',
        help='Ex : 5000,10000,25000,50000 — boutons de saisie rapide sur le portail.',
        config_parameter='hr_dz_loan.amount_presets',
        default='5000,10000,25000,50000',
    )
