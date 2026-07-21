from odoo import http
from odoo.http import request
from odoo.addons.hr_dz_requests.controllers.portal import HrRequestsPortal


class HrLoanPortal(HrRequestsPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'active_loan' in counters:
            employee = request.env['hr.employee'].sudo().search(
                [('user_id', '=', request.env.user.id)], limit=1
            )
            active_loan = False
            next_line = False
            if employee:
                active_loan = request.env['hr.loan'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['approved', 'ongoing']),
                ], order='date_approval desc', limit=1)
                if active_loan:
                    next_line = request.env['hr.loan.line'].sudo().search([
                        ('loan_id', '=', active_loan.id),
                        ('paid', '=', False),
                    ], order='date asc', limit=1)
            values['active_loan'] = active_loan or False
            values['loan_next_line'] = next_line or False
        return values

    def _hr_extra_form_data(self, kw):
        data = super()._hr_extra_form_data(kw)
        data.update({
            'hr_loan_amount':    kw.get('hr_loan_amount', ''),
            'hr_loan_nb_months': kw.get('hr_loan_nb_months', 6),
            'hr_loan_reason':    kw.get('hr_loan_reason', ''),
        })
        return data

    def _hr_extra_ticket_vals(self, selected_type, form_data, kw):
        vals = super()._hr_extra_ticket_vals(selected_type, form_data, kw)
        if selected_type and selected_type.code == 'LOAN':
            try:
                amount = float(form_data.get('hr_loan_amount') or 0)
            except (ValueError, TypeError):
                amount = 0
            try:
                nb = int(form_data.get('hr_loan_nb_months') or 6)
            except (ValueError, TypeError):
                nb = 6
            vals.update({
                'hr_loan_amount':    amount,
                'hr_loan_nb_months': nb,
                'hr_loan_reason':    form_data.get('hr_loan_reason') or False,
            })
        return vals

    def _hr_extra_template_values(self, selected_type):
        values = super()._hr_extra_template_values(selected_type)
        params = http.request.env['ir.config_parameter'].sudo()
        max_amount = float(params.get_param('hr_dz_loan.max_amount', '0') or 0)
        presets_raw = params.get_param('hr_dz_loan.amount_presets', '5000,10000,25000,50000')
        presets = []
        for p in (presets_raw or '').split(','):
            try:
                v = int(float(p.strip()))
                if v > 0:
                    presets.append(v)
            except (ValueError, TypeError):
                pass
        values['loan_max_amount'] = max_amount if max_amount > 0 else False
        values['loan_amount_presets'] = presets
        return values

    def _hr_validate_form(self, selected_type, form_data):
        error = super()._hr_validate_form(selected_type, form_data)
        if error:
            return error
        if selected_type and selected_type.code == 'LOAN':
            try:
                amount = float(form_data.get('hr_loan_amount') or 0)
            except (ValueError, TypeError):
                amount = 0
            if amount <= 0:
                return 'loan_amount'
            try:
                nb = int(form_data.get('hr_loan_nb_months') or 0)
            except (ValueError, TypeError):
                nb = 0
            if nb <= 0:
                return 'loan_months'
            if not str(form_data.get('hr_loan_reason', '')).strip():
                return 'loan_reason'
        return ''

    def _hr_auto_subject(self, selected_type, form_data):
        if selected_type and selected_type.code == 'LOAN':
            amount = form_data.get('hr_loan_amount') or '?'
            nb = form_data.get('hr_loan_nb_months') or '?'
            return 'Prêt salarial — %s DA — %s mois' % (amount, nb)
        return super()._hr_auto_subject(selected_type, form_data)
