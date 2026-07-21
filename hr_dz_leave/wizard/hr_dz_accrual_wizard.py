from datetime import date, timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError


class HrDzAccrualWizard(models.TransientModel):
    _name = 'hr.dz.accrual.wizard'
    _description = "Wizard — Affectation congé annuel DZ"

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employés',
        help="Laisser vide pour traiter tous les employés actifs",
    )
    date_from = fields.Date(
        string='Du',
        required=True,
        default=lambda self: date(date.today().year, 1, 1),
    )
    date_to = fields.Date(
        string='Au',
        required=True,
        default=lambda self: date.today() - timedelta(days=1),
    )
    backfill = fields.Boolean(
        string='Recalculer depuis le pointage',
        default=True,
        help="Recompte tous les jours pointés entre 'Du' et 'Au' et crée/met à jour "
             "l'allocation avec le total calculé.\n"
             "Utile pour la mise en place initiale ou correction en cours d'année.",
    )
    force_recreate = fields.Boolean(
        string='Mettre à jour si déjà existant',
        default=False,
        help="Si une allocation existe déjà pour l'année, la recalcule depuis le pointage.",
    )
    result_message = fields.Text(string='Résultat', readonly=True)

    def action_create_allocations(self):
        self.ensure_one()

        if self.date_from > self.date_to:
            raise UserError(_("La date de début doit être antérieure à la date de fin."))

        leave_type = self.env.ref('hr_dz_leave.leave_type_annual_dz')
        alloc_model = self.env['hr.leave.allocation']
        year = self.date_from.year

        employees = self.employee_ids or self.env['hr.employee'].search([
            ('active', '=', True)])
        if not employees:
            raise UserError(_("Aucun employé actif trouvé."))

        created = updated = skipped = 0
        skipped_names = []

        for emp in employees:
            existing = alloc_model.search([
                ('employee_id', '=', emp.id),
                ('holiday_status_id', '=', leave_type.id),
                ('allocation_type', '=', 'regular'),
                ('date_from', '>=', date(year, 1, 1)),
                ('date_from', '<=', date(year, 12, 31)),
                ('state', '=', 'validate'),
            ], limit=1)

            if existing and not self.force_recreate:
                skipped += 1
                skipped_names.append(emp.name)
                continue

            # Calculer les jours depuis le pointage (backfill)
            total_days = 0.0
            if self.backfill:
                total_days = alloc_model._dz_compute_historical(
                    emp, self.date_from, self.date_to, leave_type)

            if existing:
                # Mise à jour du solde
                existing.sudo().write({'number_of_days': total_days or existing.number_of_days})
                updated += 1
                continue

            if total_days <= 0:
                # Pas de pointage trouvé : le cron créera l'allocation au 1er jour travaillé
                skipped += 1
                skipped_names.append('%s (0j pointage)' % emp.name)
                continue

            alloc = alloc_model.sudo().create({
                'name': 'Congé annuel %d' % year,
                'holiday_status_id': leave_type.id,
                'employee_id': emp.id,
                'allocation_type': 'regular',
                'date_from': date(year, 1, 1),
                'number_of_days': total_days,
            })
            if alloc.state != 'validate':
                alloc.sudo().action_confirm()
                alloc.sudo().action_validate()
            created += 1

        lines = []
        if created:
            lines.append(_("%d allocation(s) créée(s).", created))
        if updated:
            lines.append(_("%d allocation(s) mise(s) à jour.", updated))
        if skipped:
            lines.append(_("%d ignoré(s) : %s", skipped, ', '.join(skipped_names)))
        if not lines:
            lines.append(_("Aucune action effectuée."))

        self.result_message = '\n'.join(lines)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
