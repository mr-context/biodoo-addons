
from odoo import models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def action_open_payslip_analysis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Éléments de paie — %s') % self.name,
            'res_model': 'hr.payslip.line',
            'view_mode': 'pivot,list',
            'views': [
                (self.env.ref('hr_dz_payroll.hr_payslip_line_pivot_dz').id, 'pivot'),
                (self.env.ref('hr_dz_payroll.hr_payslip_line_list_dz').id, 'list'),
            ],
            'domain': [
                ('employee_id', '=', self.id),
                ('slip_id.state', 'in', ['done', 'paid']),
            ],
            'context': {
                'search_default_group_month': 1,
                'search_view_id': self.env.ref('hr_dz_payroll.hr_payslip_line_search_dz').id,
            },
        }

    def action_open_releve_emoluments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Relevé des Émoluments',
            'res_model': 'hr.dz.releve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_employee_id': self.id},
        }
