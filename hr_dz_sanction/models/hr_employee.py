from odoo import models, fields, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    sanction_count = fields.Integer(
        string='Procédures disciplinaires',
        compute='_compute_sanction_count',
    )

    def _compute_sanction_count(self):
        for emp in self:
            emp.sanction_count = self.env['hr.sanction'].search_count([
                ('employee_id', '=', emp.id),
                ('state', '!=', 'cancel'),
            ])

    def action_view_sanctions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dossier disciplinaire'),
            'res_model': 'hr.sanction',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
