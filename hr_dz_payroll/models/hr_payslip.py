"""
Extension de hr.payslip pour l'Algérie.
Le bulletin lit les prestations (hr.work.entry) pour calculer les worked_days.
"""

from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # ── Override onchange pour éviter le calcul auto des worked_days ──
    # Notre module utilise le bouton "Charger prestations" qui lit les
    # hr.work.entry au lieu du calcul théorique du calendrier.
    # Le calcul de base (_compute_leave_days) peut produire code=False
    # quand il y a des congés globaux (jours fériés) sans hr.leave lié.

    @api.onchange("date_from", "date_to")
    def onchange_dates(self):
        """Skip base worked_days computation - we use 'Charger prestations'."""
        return

    def _compute_leave_days(self, contract, day_from, day_to):
        """Fix: ensure code is never False in leave computation."""
        leaves = super()._compute_leave_days(contract, day_from, day_to)
        for leave_vals in leaves:
            if not leave_vals.get('code'):
                leave_vals['code'] = 'GLOBAL'
        return leaves

    work_entries_generated = fields.Boolean(
        string='Chargé depuis prestations',
        default=False,
        help='Indique si les worked_days ont été chargés depuis les prestations',
    )
    work_entry_summary = fields.Text(
        string='Résumé des prestations',
        compute='_compute_work_entry_summary',
    )

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_work_entry_summary(self):
        """Calcule un résumé des prestations pour la période"""
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                payslip.work_entry_summary = ''
                continue

            work_entries = self._get_work_entries_for_period(
                payslip.employee_id, payslip.date_from, payslip.date_to
            )
            if not work_entries:
                payslip.work_entry_summary = _('Aucune prestation trouvée pour cette période')
                continue

            # Grouper par type
            by_type = defaultdict(float)
            for entry in work_entries:
                key = entry.work_entry_type_id.code or entry.work_entry_type_id.name or '?'
                by_type[key] += entry.duration

            summary_lines = [_("Prestations: %d") % len(work_entries)]
            for code, hours in sorted(by_type.items()):
                summary_lines.append(f"  {code}: {hours:.2f}h")

            payslip.work_entry_summary = '\n'.join(summary_lines)

    def _get_work_entries_for_period(self, employee, date_from, date_to):
        """Récupère les prestations d'un employé pour une période"""
        return self.env['hr.work.entry'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ], order='date')

    def action_load_from_work_entries(self):
        """
        Charge les worked_days depuis les prestations (hr.work.entry).
        C'est le point d'entrée pour la paie.
        """
        for payslip in self:
            if payslip.state not in ('draft', 'verify'):
                raise UserError(_('Impossible de modifier un bulletin validé ou annulé.'))

            work_entries = self._get_work_entries_for_period(
                payslip.employee_id, payslip.date_from, payslip.date_to
            )

            if not payslip.contract_id:
                raise UserError(_(
                    'Aucun contrat trouvé pour %(employee)s. '
                    'Veuillez assigner un contrat avant de charger les prestations.'
                ) % {'employee': payslip.employee_id.name})

            if not work_entries:
                raise UserError(_(
                    'Aucune prestation trouvée pour %(employee)s '
                    'entre %(date_from)s et %(date_to)s.\n\n'
                    'Générez d\'abord les prestations depuis le menu Paie → Prestations.'
                ) % {
                    'employee': payslip.employee_id.name,
                    'date_from': payslip.date_from,
                    'date_to': payslip.date_to,
                })

            # Grouper les prestations par type (code)
            entries_by_type = defaultdict(
                lambda: {'hours': 0.0, 'days': set(), 'name': '', 'type_id': False})
            for entry in work_entries:
                code = entry.work_entry_type_id.code or 'WORK'
                entries_by_type[code]['hours'] += entry.duration
                entries_by_type[code]['days'].add(entry.date)
                entries_by_type[code]['name'] = entry.work_entry_type_id.name
                # Stocker l'id du type — utilisé dans les règles salariales
                # pour la détection dynamique (is_paid, is_standard_work…)
                if not entries_by_type[code]['type_id']:
                    entries_by_type[code]['type_id'] = entry.work_entry_type_id.id

            # Préparer les valeurs des worked_days
            worked_days_vals = []
            sequence = 1

            for code, data in sorted(entries_by_type.items()):
                worked_days_vals.append({
                    'name': data['name'],
                    'sequence': sequence,
                    'code': code,
                    'number_of_days': len(data['days']),
                    'number_of_hours': data['hours'],
                    'contract_id': payslip.contract_id.id if payslip.contract_id else False,
                    'work_entry_type_id': data['type_id'],
                })
                sequence += 1

            # Supprimer les anciennes lignes worked_days
            payslip.worked_days_line_ids.unlink()

            # Créer les nouvelles lignes
            for vals in worked_days_vals:
                vals['payslip_id'] = payslip.id
                self.env['hr.payslip.worked_days'].create(vals)

            # ── Recharger les autres entrées (inputs : LOAN_REPAY, etc.) ──
            contracts = payslip._get_employee_contracts()
            if contracts:
                input_vals = payslip.get_inputs(
                    contracts, payslip.date_from, payslip.date_to)
                payslip.input_line_ids.unlink()
                seq = 1
                for iv in input_vals:
                    contract_id = iv.get('contract_id') or contracts[0].id
                    self.env['hr.payslip.input'].create({
                        'payslip_id': payslip.id,
                        'name':        iv.get('name', ''),
                        'code':        iv.get('code', ''),
                        'contract_id': contract_id,
                        'amount':      iv.get('amount', 0.0),
                        'sequence':    seq,
                    })
                    seq += 1

            payslip.work_entries_generated = True

        return True

    def action_view_work_entries(self):
        """Ouvre la vue des prestations pour la période du bulletin"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Prestations'),
            'res_model': 'hr.work.entry',
            'view_mode': 'list,form',
            'domain': [
                ('employee_id', '=', self.employee_id.id),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ],
            'context': {
                'default_employee_id': self.employee_id.id,
            },
        }
