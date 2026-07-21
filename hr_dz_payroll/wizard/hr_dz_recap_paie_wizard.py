
import calendar
from datetime import date

from odoo import models, fields, _
from odoo.exceptions import UserError

MONTHS = [
    ('1', 'Janvier'), ('2', 'Février'), ('3', 'Mars'), ('4', 'Avril'),
    ('5', 'Mai'), ('6', 'Juin'), ('7', 'Juillet'), ('8', 'Août'),
    ('9', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre'),
]


class HrDzRecapPaieWizard(models.TransientModel):
    _name = 'hr.dz.recap.paie.wizard'
    _description = 'Récapitulatif Mensuel de Paie'

    month = fields.Selection(
        MONTHS, string='Mois', required=True,
        default=lambda self: str(date.today().month),
    )
    year = fields.Integer(
        string='Année', required=True,
        default=lambda self: date.today().year,
    )

    def get_report_data(self):
        """Appelé depuis le template QWeb."""
        self.ensure_one()
        m = int(self.month)
        y = self.year
        date_from = date(y, m, 1)
        date_to = date(y, m, calendar.monthrange(y, m)[1])

        payslips = self.env['hr.payslip'].search([
            ('state', '=', 'done'),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
        ], order='employee_id')

        if not payslips:
            raise UserError(_(
                'Aucun bulletin confirmé pour %s %s.'
            ) % (dict(MONTHS)[self.month], y))

        lines = []
        for slip in payslips:
            def get_rule(code, s=slip):
                line = s.line_ids.filtered(lambda l: l.code == code)
                return line[:1].total if line else 0.0

            lines.append({
                'employee': slip.employee_id.name,
                'matricule': slip.employee_id.matricule or '',
                'brut': get_rule('BASIC'),
                'imposable': get_rule('IMPOSABLE'),
                'net': get_rule('NET'),
            })
        return lines

    def action_print(self):
        self.ensure_one()
        self.get_report_data()
        return self.env.ref('hr_dz_payroll.action_report_recap_paie').report_action(self)
