import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    """
    Injecte automatiquement la mensualité de prêt dans les "Autres entrées"
    lors du chargement du bulletin de paie.
    """
    _inherit = 'hr.payslip'

    def _get_loan_employee(self, contracts):
        """Retourne l'employé lié à ce bulletin (self ou via le contrat)."""
        # Cas 1 : self est un bulletin réel (appelé depuis onchange_struct_id)
        if self and self.employee_id:
            return self.employee_id
        # Cas 2 : self est vide (appelé depuis get_payslip_vals @api.model)
        if contracts:
            return contracts[0].employee_id
        return self.env['hr.employee']

    def get_inputs(self, contracts, date_from, date_to):
        res = super().get_inputs(contracts, date_from, date_to)

        employee = self._get_loan_employee(contracts)
        if not employee:
            return res

        LoanLine = self.env['hr.loan.line'].sudo()

        # Recherche prioritaire : mensualité dont la date est dans la période
        line = LoanLine.search([
            ('loan_id.employee_id', '=', employee.id),
            ('loan_id.state', 'in', ['approved', 'ongoing']),
            ('paid', '=', False),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ], order='date asc', limit=1)

        if not line:
            # Fallback : première mensualité non payée (date décalée ou approuvé en fin de mois)
            line = LoanLine.search([
                ('loan_id.employee_id', '=', employee.id),
                ('loan_id.state', 'in', ['approved', 'ongoing']),
                ('paid', '=', False),
            ], order='date asc', limit=1)

        if line:
            contract_id = contracts[0].id if contracts else False
            res.append({
                'name': _('Remboursement prêt salarial (%s)') % line.loan_id.name,
                'code': 'LOAN_REPAY',
                'contract_id': contract_id,
                'amount': line.amount,
            })
            _logger.info(
                'LOAN_REPAY injecté pour %s : %s DA (prêt %s, mensualité %s)',
                employee.name, line.amount, line.loan_id.name, line.date,
            )

        return res

    def action_payslip_done(self):
        """
        À la validation du bulletin, marquer la mensualité comme payée.
        """
        res = super().action_payslip_done()
        LoanLine = self.env['hr.loan.line'].sudo()

        for payslip in self:
            loan_input = payslip.input_line_ids.filtered(
                lambda l: l.code == 'LOAN_REPAY' and l.amount > 0
            )
            if not loan_input:
                continue

            employee = payslip.employee_id
            # Chercher la mensualité non payée la plus ancienne pour cet employé
            line = LoanLine.search([
                ('loan_id.employee_id', '=', employee.id),
                ('loan_id.state', 'in', ['approved', 'ongoing']),
                ('paid', '=', False),
            ], order='date asc', limit=1)

            if line:
                line.write({
                    'paid': True,
                    'date_paid': payslip.date_to,
                    'payslip_id': payslip.id,
                    'amount': loan_input.amount,
                })
                line.loan_id._check_close()
                _logger.info(
                    'Mensualité prêt %s marquée payée via bulletin %s.',
                    line.loan_id.name, payslip.name,
                )
            else:
                _logger.warning(
                    'LOAN_REPAY présent sur bulletin %s mais aucune mensualité trouvée pour %s.',
                    payslip.name, employee.name,
                )

        return res
