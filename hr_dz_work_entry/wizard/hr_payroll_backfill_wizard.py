"""
Wizard de rattrapage pipeline paie.
Génère les work entries + payslips brouillon pour tous les mois
depuis une date de départ, pour les employés sélectionnés.
"""

import logging
from datetime import date as date_cls, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayrollBackfillWizard(models.TransientModel):
    _name = 'hr.payroll.backfill.wizard'
    _description = 'Rattrapage pipeline paie'

    date_from = fields.Date(
        string='Depuis le',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        help="Date de départ du rattrapage. Le wizard traitera tous les mois "
             "depuis cette date jusqu'au mois en cours.",
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employés',
        help="Laisser vide pour traiter tous les employés de la société.",
    )

    def _iter_months(self, date_from):
        """Génère les couples (month_start, month_end) de date_from au mois courant."""
        today = date_cls.today()
        current = date_from.replace(day=1)
        while current <= today.replace(day=1):
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1, day=1)
            else:
                next_month = current.replace(month=current.month + 1, day=1)
            month_end = next_month - timedelta(days=1)
            yield current, month_end
            current = next_month

    def action_run(self):
        """Lance le rattrapage pipeline mois par mois."""
        self.ensure_one()

        company = self.env.company
        if not company.auto_payroll_pipeline:
            raise UserError(_(
                "Le pipeline paie automatique n'est pas activé. "
                "Activez-le dans Paramètres → Employés avant de lancer le rattrapage."
            ))

        employees = self.employee_ids or self.env['hr.employee'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])

        if not employees:
            raise UserError(_("Aucun employé trouvé."))

        Attendance = self.env['hr.attendance']
        total_payslips = 0
        total_we = 0

        for month_start, month_end in self._iter_months(self.date_from):
            _logger.info("Backfill — mois %s → %s", month_start, month_end)

            for employee in employees:
                # Ne traiter que si l'employé a des présences complètes ce mois
                has_attendance = Attendance.search_count([
                    ('employee_id', '=', employee.id),
                    ('check_in', '>=', fields.Datetime.to_datetime(month_start)),
                    ('check_in', '<=', fields.Datetime.to_datetime(month_end)),
                    ('check_out', '!=', False),
                ])
                if not has_attendance:
                    continue

                # ── Work entries ──────────────────────────────────────────
                wizard = self.env['hr.work.entry.compute.wizard'].create({
                    'date_from': month_start,
                    'date_to': month_end,
                    'employee_ids': [(6, 0, [employee.id])],
                    'force_regenerate': False,
                })
                wizard.action_compute()
                total_we += 1

                # ── Déductions retard ─────────────────────────────────────
                if company.late_sanction_enabled:
                    deductions = self.env['hr.attendance.deduction'].search([
                        ('employee_id', '=', employee.id),
                        ('date', '>=', month_start),
                        ('date', '<=', month_end),
                        ('status', '=', 'to_validate'),
                    ])
                    if deductions:
                        deductions.action_validate()

                # ── Payslip brouillon ─────────────────────────────────────
                contract = self.env['hr.version'].search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ('active', 'draft')),
                    ('contract_date_start', '<=', month_end),
                    '|',
                    ('contract_date_end', '=', False),
                    ('contract_date_end', '>=', month_start),
                ], limit=1)

                if not contract:
                    _logger.warning(
                        "Backfill — %s %s : pas de contrat, payslip ignoré",
                        employee.name, month_start,
                    )
                    continue

                payslip = self.env['hr.payslip'].search([
                    ('employee_id', '=', employee.id),
                    ('date_from', '=', month_start),
                    ('date_to', '=', month_end),
                    ('state', 'in', ('draft', 'verify')),
                ], limit=1)

                if not payslip:
                    payslip = self.env['hr.payslip'].create({
                        'employee_id': employee.id,
                        'contract_id': contract.id,
                        'struct_id': contract.struct_id.id if contract.struct_id else False,
                        'date_from': month_start,
                        'date_to': month_end,
                        'company_id': company.id,
                    })
                    total_payslips += 1
                elif contract.struct_id and not payslip.struct_id:
                    payslip.struct_id = contract.struct_id.id

                if hasattr(payslip, 'action_load_from_work_entries'):
                    payslip.action_load_from_work_entries()
                payslip.compute_sheet()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rattrapage terminé'),
                'message': _(
                    '%d mois traités, %d payslip(s) créé(s).'
                ) % (total_we, total_payslips),
                'type': 'success',
                'sticky': False,
            },
        }
