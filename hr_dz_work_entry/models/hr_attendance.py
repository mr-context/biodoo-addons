"""
Extension de hr.attendance pour le lien avec hr.work.entry
et le pipeline paie automatique.
"""

import logging
from datetime import date as date_cls

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    work_entry_ids = fields.Many2many(
        'hr.work.entry',
        'hr_attendance_work_entry_rel',
        'attendance_id',
        'work_entry_id',
        string='Prestations liées',
        readonly=True,
    )

    # =========================================================================
    # PIPELINE PAIE AUTOMATIQUE
    # Déclenché dès que check_out est posé sur une présence complète.
    # =========================================================================

    def write(self, vals):
        # Mémoriser les présences sans check_out avant l'écriture
        if 'check_out' in vals and vals['check_out']:
            newly_complete = self.filtered(lambda a: not a.check_out)
        else:
            newly_complete = self.env['hr.attendance']

        res = super().write(vals)

        # Déclencher le pipeline pour les présences qui viennent d'être complétées
        if newly_complete:
            newly_complete._trigger_auto_pipeline()

        return res

    def _trigger_auto_pipeline(self):
        """Déclenche le pipeline paie auto si activé sur la société."""
        for attendance in self:
            company = attendance.employee_id.company_id
            if not company.auto_payroll_pipeline:
                continue
            try:
                attendance._run_auto_pipeline()
            except Exception as e:
                _logger.warning(
                    "Auto pipeline failed for attendance %s (%s): %s",
                    attendance.id, attendance.employee_id.name, e,
                )

    def _run_auto_pipeline(self):
        """Pipeline complet : work entries → déductions → payslip brouillon."""
        self.ensure_one()
        employee = self.employee_id
        company = employee.company_id
        check_in = self.check_in

        # ── Période : mois complet de la présence ─────────────────────────
        month_start = check_in.date().replace(day=1)
        # Dernier jour du mois
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)
        from datetime import timedelta
        month_end = month_end - timedelta(days=1)

        _logger.info(
            "Auto pipeline — %s : %s → %s",
            employee.name, month_start, month_end,
        )

        # ── Étape 1 : Génération des work entries ─────────────────────────
        wizard = self.env['hr.work.entry.compute.wizard'].create({
            'date_from': month_start,
            'date_to': month_end,
            'employee_ids': [(6, 0, [employee.id])],
            'force_regenerate': False,
        })
        wizard.action_compute()
        _logger.info("Auto pipeline — %s : work entries générés", employee.name)

        # ── Étape 2 : Validation déductions retard (si sanction activée) ──
        if company.late_sanction_enabled:
            deductions = self.env['hr.attendance.deduction'].search([
                ('employee_id', '=', employee.id),
                ('date', '=', check_in.date()),
                ('status', '=', 'to_validate'),
            ])
            if deductions:
                deductions.action_validate()
                _logger.info(
                    "Auto pipeline — %s : %d déduction(s) validée(s)",
                    employee.name, len(deductions),
                )

        # ── Étape 3 : Payslip brouillon du mois ──────────────────────────
        # Trouver le contrat actif
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
                "Auto pipeline — %s : aucun contrat actif, payslip ignoré",
                employee.name,
            )
            return

        # Chercher un payslip brouillon existant pour ce mois
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
            _logger.info(
                "Auto pipeline — %s : payslip créé (id=%s)",
                employee.name, payslip.id,
            )
        elif contract.struct_id and not payslip.struct_id:
            payslip.struct_id = contract.struct_id.id

        # ── Étape 4 : Charger les prestations puis recalculer ────────────
        if hasattr(payslip, 'action_load_from_work_entries'):
            payslip.action_load_from_work_entries()
        payslip.compute_sheet()
        _logger.info(
            "Auto pipeline — %s : payslip recalculé (net=%s)",
            employee.name,
            payslip.line_ids.filtered(lambda l: l.code == 'NET').mapped('total'),
        )
