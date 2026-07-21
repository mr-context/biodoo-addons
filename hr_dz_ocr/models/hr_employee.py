"""
Extension hr.employee pour le bouton OCR.
Les champs algériens sont définis dans hr_dz_base.
"""

from odoo import models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def action_open_ocr_wizard(self):
        """Ouvre le wizard OCR pour cet employé."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scanner un Document OCR'),
            'res_model': 'hr.ocr.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.id,
            },
        }
