
import calendar
from datetime import date

from odoo import models, fields, _
from odoo.exceptions import UserError


class HrDzReleveWizard(models.TransientModel):
    _name = 'hr.dz.releve.wizard'
    _description = 'Relevé des Émoluments'

    employee_id = fields.Many2one('hr.employee', string='Employé', required=True)

    mode = fields.Selection([
        ('months', "Mois de l'année"),
        ('period', 'Période libre'),
    ], string='Sélection', default='months', required=True)

    # Mode période libre
    date_from = fields.Date(string='Date début')
    date_to = fields.Date(string='Date fin')

    # Mode mois de l'année
    year = fields.Integer(string='Année', default=lambda self: date.today().year)
    month_01 = fields.Boolean(string='Janvier')
    month_02 = fields.Boolean(string='Février')
    month_03 = fields.Boolean(string='Mars')
    month_04 = fields.Boolean(string='Avril')
    month_05 = fields.Boolean(string='Mai')
    month_06 = fields.Boolean(string='Juin')
    month_07 = fields.Boolean(string='Juillet')
    month_08 = fields.Boolean(string='Août')
    month_09 = fields.Boolean(string='Septembre')
    month_10 = fields.Boolean(string='Octobre')
    month_11 = fields.Boolean(string='Novembre')
    month_12 = fields.Boolean(string='Décembre')

    def _get_payslips(self):
        if self.mode == 'period':
            if not self.date_from or not self.date_to:
                raise UserError(_('Veuillez saisir une date début et une date fin.'))
            return self.env['hr.payslip'].search([
                ('employee_id', '=', self.employee_id.id),
                ('state', '=', 'done'),
                ('date_from', '>=', self.date_from),
                ('date_to', '<=', self.date_to),
            ], order='date_from')
        else:
            selected = [i for i in range(1, 13) if getattr(self, f'month_{i:02d}')]
            if not selected:
                raise UserError(_('Veuillez sélectionner au moins un mois.'))
            payslips = self.env['hr.payslip']
            for m in selected:
                m_start = date(self.year, m, 1)
                m_end = date(self.year, m, calendar.monthrange(self.year, m)[1])
                payslips |= self.env['hr.payslip'].search([
                    ('employee_id', '=', self.employee_id.id),
                    ('state', '=', 'done'),
                    ('date_from', '>=', m_start),
                    ('date_to', '<=', m_end),
                ])
            return payslips.sorted('date_from')

    def _get_rule(self, slip, code):
        line = slip.line_ids.filtered(lambda l: l.code == code)
        return line[:1].total if line else 0.0

    def get_report_data(self):
        """Appelé depuis le template QWeb."""
        self.ensure_one()
        payslips = self._get_payslips()
        if not payslips:
            raise UserError(_(
                'Aucun bulletin confirmé trouvé pour %s sur la période sélectionnée.'
            ) % self.employee_id.name)

        lines = []
        for slip in payslips:
            nb_jours = sum(
                slip.worked_days_line_ids.filtered(
                    lambda w: w.code in ('WORK100', 'FERIE')
                ).mapped('number_of_days')
            )
            lines.append({
                'period': slip.date_from.strftime('%m/%Y'),
                'nb_jours': nb_jours,
                'brut': self._get_rule(slip, 'BASIC'),
                'imposable': self._get_rule(slip, 'IMPOSABLE'),
                'net': self._get_rule(slip, 'NET'),
            })
        return lines

    def action_print(self):
        self.ensure_one()
        self._get_payslips()
        return self.env.ref('hr_dz_payroll.action_report_releve').report_action(self)

    # Alias pour compatibilité si l'ancienne vue est encore en base
    def action_generate(self):
        return self.action_print()
