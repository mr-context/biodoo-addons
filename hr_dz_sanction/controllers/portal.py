"""
Portail employé — Procédures disciplinaires.

Routes :
  GET  /my/sanctions              → liste des procédures de l'employé
  GET  /my/sanctions/<id>         → détail + progress indicator
  POST /my/sanctions/<id>/response → soumettre la réponse d'audition
  GET  /my/sanctions/<id>/convocation.pdf → PDF convocation
  GET  /my/sanctions/<id>/decision.pdf    → PDF décision
"""

import logging

from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)

# Libellés et classes CSS par état
STATE_LABELS = {
    'draft':    'Nouveau',
    'convoque': 'Convoqué',
    'audition': 'En audition',
    'decide':   'Décision rendue',
    'notifie':  'Notifié',
    'done':     'Terminé',
    'cancel':   'Annulé',
}

STATE_BADGE = {
    'draft':    'bg-secondary',
    'convoque': 'bg-warning text-dark',
    'audition': 'bg-info text-dark',
    'decide':   'bg-primary',
    'notifie':  'bg-primary',
    'done':     'bg-success',
    'cancel':   'bg-danger',
}

# Ordre des étapes pour le progress indicator
STEPS = ['draft', 'convoque', 'audition', 'decide', 'notifie', 'done']


class SanctionPortal(CustomerPortal):

    # ── Données de notification — disponibles sur TOUTES les pages portail ──
    #
    # On surcharge _prepare_portal_layout_values (appelée par chaque page
    # portail pour le rendu HTML) et NON _prepare_home_portal_values qui
    # alimente aussi la route JSON-RPC /my/counters — celle-ci n'accepte
    # que des valeurs JSON-sérialisables (pas de recordsets).

    def _prepare_portal_layout_values(self):
        """Ajoute sanction_portal_notifications et sanction_unread_count
        aux valeurs de layout disponibles dans toutes les pages portail."""
        values = super()._prepare_portal_layout_values()
        employee = self._get_sanction_employee()
        if employee:
            notifications = request.env['hr.sanction'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ('convoque', 'audition', 'decide', 'notifie')),
            ], order='date_incident desc')
            values['sanction_portal_notifications'] = notifications
            values['sanction_unread_count'] = sum(
                1 for n in notifications if not n.portal_read
            )
        else:
            values['sanction_portal_notifications'] = (
                request.env['hr.sanction'].sudo().browse()
            )
            values['sanction_unread_count'] = 0
        return values

    # ── Compteur home portal (JSON-safe) ──────────────────────────────
    #
    # Seules les valeurs JSON-sérialisables (int, bool, str…) peuvent
    # être retournées ici — la route /my/counters (JSON-RPC) appelle
    # cette méthode et retourne le résultat directement en JSON.
    # Ne jamais y mettre un recordset Odoo.

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'sanction_count' in counters:
            employee = self._get_sanction_employee()
            values['sanction_count'] = (
                request.env['hr.sanction'].sudo().search_count([
                    ('employee_id', '=', employee.id),
                    ('state', 'not in', ('cancel',)),   # actif + terminé
                ]) if employee else 0
            )
        return values

    # ── Home portal ────────────────────────────────────────────────────
    #
    # On override home() pour inclure les layout values (notifications)
    # dans le rendu HTML de /my — CustomerPortal.home() ne les inclut pas.

    @http.route(['/my', '/my/home'], type='http', auth='user', website=True)
    def home(self, **kw):
        """Portail home — inclut les notifications sanctions."""
        values = self._prepare_home_portal_values([])
        values.update(self._prepare_portal_layout_values())
        return request.render('portal.portal_my_home', values)

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_sanction_employee(self):
        """Retourne l'hr.employee lié à l'utilisateur connecté, en sudo."""
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )

    def _check_sanction_access(self, sanction_id):
        """
        Vérifie que la sanction appartient bien à l'employé connecté.
        Retourne (sanction_sudo, employee_sudo) ou (None, None).
        """
        employee = self._get_sanction_employee()
        if not employee:
            return None, None
        sanction = request.env['hr.sanction'].sudo().browse(sanction_id)
        if not sanction.exists() or sanction.employee_id.id != employee.id:
            return None, None
        return sanction, employee

    # ── Route : liste ─────────────────────────────────────────────────

    @http.route('/my/sanctions', type='http', auth='user', website=True)
    def portal_my_sanctions(self, **kw):
        employee = self._get_sanction_employee()
        sanctions = (
            request.env['hr.sanction'].sudo().search(
                [('employee_id', '=', employee.id), ('state', '!=', 'cancel')],
                order='date_incident desc',
            )
            if employee
            else request.env['hr.sanction'].sudo().browse()
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'sanctions': sanctions,
            'page_name': 'sanctions',
            'state_labels': STATE_LABELS,
            'state_badge': STATE_BADGE,
        })
        return request.render('hr_dz_sanction.portal_my_sanctions', values)

    # ── Route : détail ────────────────────────────────────────────────

    @http.route('/my/sanctions/<int:sanction_id>', type='http',
                auth='user', website=True)
    def portal_sanction_detail(self, sanction_id, **kw):
        sanction, employee = self._check_sanction_access(sanction_id)
        if not sanction:
            return request.redirect('/my/sanctions')

        # Marquer comme lu dès que l'employé ouvre la page
        if not sanction.portal_read:
            sanction.sudo().write({'portal_read': True})

        # Index de l'état dans les étapes pour le progress indicator
        current_step = STEPS.index(sanction.state) if sanction.state in STEPS else 0

        values = self._prepare_portal_layout_values()
        values.update({
            'sanction': sanction,
            'employee': employee,
            'page_name': 'sanctions',
            'state_labels': STATE_LABELS,
            'state_badge': STATE_BADGE,
            'steps': STEPS,
            'current_step': current_step,
            'response_sent': kw.get('response_sent') == '1',
        })
        return request.render('hr_dz_sanction.portal_sanction_detail', values)

    # ── Route POST : réponse d'audition ───────────────────────────────

    @http.route('/my/sanctions/<int:sanction_id>/response', type='http',
                auth='user', website=True, methods=['POST'])
    def portal_sanction_response(self, sanction_id, employee_response='', **kw):
        sanction, employee = self._check_sanction_access(sanction_id)
        if not sanction or sanction.state != 'audition':
            return request.redirect('/my/sanctions')

        response_text = (employee_response or '').strip()
        if response_text:
            sanction.sudo().write({'employee_response': response_text})
            sanction.sudo().message_post(
                body=(
                    '<b>Réponse de l\'employé soumise depuis le portail :</b>'
                    '<br/>%s' % response_text
                ),
                subtype_xmlid='mail.mt_comment',
                author_id=request.env.user.partner_id.id,
            )
            _logger.info(
                'Sanction %s : réponse portail soumise par %s',
                sanction.name, request.env.user.login,
            )

        return request.redirect('/my/sanctions/%d?response_sent=1' % sanction_id)

    # ── Route PDF : convocation ───────────────────────────────────────

    @http.route('/my/sanctions/<int:sanction_id>/convocation.pdf',
                type='http', auth='user', website=True)
    def portal_sanction_convocation_pdf(self, sanction_id, **kw):
        sanction, _emp = self._check_sanction_access(sanction_id)
        if not sanction or sanction.state == 'draft':
            return request.redirect('/my/sanctions')

        report = request.env.ref(
            'hr_dz_sanction.report_action_convocation'
        ).sudo()
        pdf_content, _mime = report._render_qweb_pdf(
            'hr_dz_sanction.report_convocation_document',
            res_ids=[sanction_id],
        )
        filename = 'Convocation_%s.pdf' % (sanction.name or sanction_id)
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ],
        )

    # ── Route PDF : décision ──────────────────────────────────────────

    @http.route('/my/sanctions/<int:sanction_id>/decision.pdf',
                type='http', auth='user', website=True)
    def portal_sanction_decision_pdf(self, sanction_id, **kw):
        sanction, _emp = self._check_sanction_access(sanction_id)
        if not sanction or sanction.state not in ('decide', 'notifie', 'done'):
            return request.redirect('/my/sanctions')

        report = request.env.ref(
            'hr_dz_sanction.report_action_decision'
        ).sudo()
        pdf_content, _mime = report._render_qweb_pdf(
            'hr_dz_sanction.report_decision_document',
            res_ids=[sanction_id],
        )
        filename = 'Decision_%s.pdf' % (sanction.name or sanction_id)
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ],
        )
