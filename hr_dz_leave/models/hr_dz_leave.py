import logging
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    dz_last_accrual_date = fields.Date(
        string='Dernier calcul DZ',
        readonly=True,
        help="Date du dernier pointage pris en compte pour le calcul journalier DZ",
    )

    # -------------------------------------------------------------------------
    # CRON JOURNALIER
    # -------------------------------------------------------------------------

    @api.model
    def _cron_dz_daily_leave_accrual(self):
        """Cron journalier (6h) : crédite la portion du jour précédent si pointage complet."""
        yesterday = date.today() - timedelta(days=1)
        leave_type = self.env.ref(
            'hr_dz_leave.leave_type_annual_dz', raise_if_not_found=False)
        if not leave_type:
            _logger.warning("DZ Leave: type de congé 'leave_type_annual_dz' introuvable.")
            return

        employees = self.env['hr.employee'].search([('active', '=', True)])
        for emp in employees:
            try:
                self._dz_process_employee_day(emp, yesterday, leave_type)
            except Exception:
                _logger.exception(
                    "DZ Leave accrual: erreur pour l'employé %s (id=%d)",
                    emp.name, emp.id)

    # -------------------------------------------------------------------------
    # TRAITEMENT PAR JOUR / EMPLOYÉ
    # -------------------------------------------------------------------------

    @api.model
    def _dz_process_employee_day(self, emp, target_date, leave_type):
        """
        Vérifie si l'employé a un pointage complet pour target_date.
        Si oui, ajoute taux/jours_ouvrables à son allocation annuelle.
        """
        year = target_date.year

        # -- Trouver l'allocation de l'année en cours --
        allocation = self.search([
            ('employee_id', '=', emp.id),
            ('holiday_status_id', '=', leave_type.id),
            ('allocation_type', '=', 'regular'),
            ('date_from', '>=', date(year, 1, 1)),
            ('date_from', '<=', date(year, 12, 31)),
            ('state', '=', 'validate'),
        ], limit=1)

        # Eviter double traitement
        if allocation and allocation.dz_last_accrual_date == target_date:
            return

        # -- Vérifier pointage complet (check_in ET check_out) --
        dt_start = datetime.combine(target_date, time.min)
        dt_end = datetime.combine(target_date + timedelta(days=1), time.min)
        has_attendance = self.env['hr.attendance'].search_count([
            ('employee_id', '=', emp.id),
            ('check_in', '>=', dt_start),
            ('check_in', '<', dt_end),
            ('check_out', '!=', False),
        ])
        if not has_attendance:
            return

        # -- Calculer la portion journalière --
        version = emp.current_version_id
        rate = float(version.dz_leave_accrual_rate or '2.5') if version else 2.5
        calendar = (
            version.resource_calendar_id if version else None
        ) or emp.resource_calendar_id

        working_days = self._dz_working_days_in_month(calendar, target_date)
        daily_portion = round(rate / working_days, 6)

        # -- Mettre à jour ou créer l'allocation --
        if allocation:
            allocation.sudo().write({
                'number_of_days': allocation.number_of_days + daily_portion,
                'dz_last_accrual_date': target_date,
            })
        else:
            alloc = self.sudo().create({
                'name': 'Congé annuel %d' % year,
                'holiday_status_id': leave_type.id,
                'employee_id': emp.id,
                'allocation_type': 'regular',
                'date_from': date(year, 1, 1),
                'number_of_days': daily_portion,
                'dz_last_accrual_date': target_date,
            })
            if alloc.state != 'validate':
                alloc.sudo().action_confirm()
                alloc.sudo().action_validate()

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    @api.model
    def _dz_working_days_in_month(self, calendar, target_date):
        """
        Retourne le nombre de jours ouvrables du mois selon le calendrier
        de travail de l'employé. Fallback : 22 jours.
        """
        year, month = target_date.year, target_date.month
        days_in_month = monthrange(year, month)[1]

        if calendar and calendar.attendance_ids:
            working_weekdays = {int(a.dayofweek) for a in calendar.attendance_ids}
        else:
            # Algérie : lundi–jeudi + vendredi (5 jours) par défaut
            working_weekdays = {0, 1, 2, 3, 4}

        count = sum(
            1 for day in range(1, days_in_month + 1)
            if date(year, month, day).weekday() in working_weekdays
        )
        return count or 22

    @api.model
    def _dz_compute_historical(self, emp, date_from, date_to, leave_type):
        """
        Calcule le cumul de droits au congé depuis l'historique pointage.
        Utilisé par le wizard lors du backfill initial.
        Retourne le total de jours arrondis à 4 décimales.
        """
        version = emp.current_version_id
        rate = float(version.dz_leave_accrual_rate or '2.5') if version else 2.5
        calendar = (
            version.resource_calendar_id if version else None
        ) or emp.resource_calendar_id

        # Tous les jours distincts pointés (check_in + check_out) dans la période
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', emp.id),
            ('check_in', '>=', datetime.combine(date_from, time.min)),
            ('check_in', '<', datetime.combine(date_to + timedelta(days=1), time.min)),
            ('check_out', '!=', False),
        ])
        worked_days = {att.check_in.date() for att in attendances}

        # Regrouper par mois pour appliquer le bon diviseur à chaque mois
        by_month = {}
        for d in worked_days:
            by_month.setdefault((d.year, d.month), 0)
            by_month[(d.year, d.month)] += 1

        total = sum(
            rate / self._dz_working_days_in_month(calendar, date(yr, mo, 1)) * count
            for (yr, mo), count in by_month.items()
        )
        return round(total, 4)
