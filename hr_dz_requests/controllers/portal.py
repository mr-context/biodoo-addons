import logging

from markupsafe import Markup, escape

from odoo import _, fields, http
from odoo.http import request
from odoo.addons.assistance.controllers.portal import AssistancePortal

_logger = logging.getLogger(__name__)

# Sélections — miroir des champs Python pour les labels dans le template
TRANSPORT_LABELS = {
    'car_service':  'Véhicule de service',
    'car_personal': 'Véhicule personnel',
    'train':        'Train',
    'plane':        'Avion',
    'taxi':         'Taxi / Transport en commun',
    'other':        'Autre',
}
SORTIE_REASON_LABELS = {
    'service':        'Raison de service',
    'administrative': 'Démarche administrative',
    'medical':        'Rendez-vous médical',
    'personal':       'Motif personnel',
    'other':          'Autre',
}


class HrRequestsPortal(AssistancePortal):
    """
    Étend /my/assistance/new et /my/assistance/<id> pour les demandes RH.

    Flux :
      GET  ?team_id=X              → sélecteur de types  (si l'équipe en a)
      GET  ?team_id=X&type_id=Y   → formulaire enrichi par type
      POST                         → crée assistance.ticket avec champs HR
      (sans types RH)              → délègue à super() — comportement standard
    """

    @http.route('/my/assistance/new', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_assistance_new(self, name=None, team_id=None, description=None,
                              # bypass : affiche le formulaire générique même si l'équipe a des types
                              generic=None,
                              # champs HR communs
                              type_id=None,
                              date_start=None, date_end=None,
                              hr_justification=None,
                              # MISSION
                              hr_mission_object=None, hr_destination=None,
                              hr_transport_mode=None, hr_advance_amount=None,
                              hr_companions=None,
                              # SORTIE
                              hr_departure_time=None, hr_return_time=None,
                              hr_sortie_reason=None, hr_sortie_destination=None,
                              hr_vehicle_requested=None,
                              hr_will_return=None,
                              # CONGE
                              hr_leave_reason=None, hr_replacement_name=None,
                              **kw):

        teams = request.env['assistance.team'].sudo().search(
            [('privacy_visibility', '=', 'portal')]
        )

        # ---- Équipe pré-sélectionnée ----
        preselected_team = None
        if team_id:
            try:
                tid = int(team_id)
                preselected_team = teams.filtered(lambda t: t.id == tid)[:1]
            except (ValueError, TypeError):
                pass

        # ---- Types RH de cette équipe ----
        team_request_types = request.env['hr.request.type'].sudo().browse()
        if preselected_team:
            team_request_types = request.env['hr.request.type'].sudo().search(
                [('active', '=', True), ('team_id', '=', preselected_team.id)]
            )

        # Aucun type RH, ou demande générique explicite → formulaire assistance standard
        if not team_request_types or generic:
            return super().portal_assistance_new(
                name=name, team_id=team_id, description=description, **kw
            )

        # ---- Type sélectionné ----
        selected_type = None
        if type_id:
            try:
                rtid = int(type_id)
                selected_type = team_request_types.filtered(
                    lambda t: t.id == rtid
                )[:1]
            except (ValueError, TypeError):
                pass

        # GET sans type → sélecteur de types
        if request.httprequest.method == 'GET' and not selected_type:
            values = self._prepare_portal_layout_values()
            values.update({
                'preselected_team': preselected_team,
                'team_request_types': team_request_types,
                'page_name': 'assistance_new',
            })
            return request.render('hr_dz_requests.portal_hr_type_picker', values)

        # ---- form_data : données pour re-peupler le formulaire en cas d'erreur ----
        form_data = self._hr_extra_form_data(kw)
        form_data.update({
            'name': name or '',
            'date_start': date_start or '',
            'date_end': date_end or '',
            'hr_justification': hr_justification or '',
            # MISSION
            'hr_mission_object': hr_mission_object or '',
            'hr_destination': hr_destination or '',
            'hr_transport_mode': hr_transport_mode or '',
            'hr_advance_amount': hr_advance_amount or '',
            'hr_companions': hr_companions or '',
            # SORTIE
            'hr_departure_time': hr_departure_time or '',
            'hr_return_time': hr_return_time or '',
            'hr_sortie_reason': hr_sortie_reason or '',
            'hr_sortie_destination': hr_sortie_destination or '',
            'hr_vehicle_requested': bool(hr_vehicle_requested),
            'hr_will_return': hr_will_return or 'yes',
            # CONGE
            'hr_leave_reason': hr_leave_reason or '',
            'hr_replacement_name': hr_replacement_name or '',
        })

        # ---- POST : création ----
        if request.httprequest.method == 'POST':
            error = self._hr_validate_form(selected_type, form_data)

            if not error:
                # Auto-génération du sujet si vide
                subject = (name or '').strip()
                if not subject:
                    subject = self._hr_auto_subject(selected_type, form_data)

                # Étape Kanban initiale
                if preselected_team:
                    stage = request.env['assistance.stage'].sudo().search(
                        ['|', ('team_ids', 'in', preselected_team.ids),
                         ('team_ids', '=', False)],
                        order='sequence, id', limit=1,
                    )
                else:
                    stage = request.env['assistance.stage'].sudo().search(
                        [], order='sequence, id', limit=1
                    )

                # Employé lié à l'utilisateur portail
                employee = request.env['hr.employee'].sudo().search(
                    [('user_id', '=', request.env.user.id)], limit=1
                )

                vals = {
                    'name': subject,
                    'partner_id': request.env.user.partner_id.id,
                    'team_id': preselected_team.id if preselected_team else False,
                    'stage_id': stage.id if stage else False,
                    'hr_request_type_id': selected_type.id if selected_type else False,
                    'hr_employee_id': employee.id if employee else False,
                    # Commun
                    'hr_date_start': date_start or False,
                    'hr_date_end': date_end or False,
                    'hr_justification': hr_justification or False,
                    # MISSION
                    'hr_mission_object': hr_mission_object or False,
                    'hr_destination': hr_destination or False,
                    'hr_transport_mode': hr_transport_mode or False,
                    'hr_advance_amount': float(hr_advance_amount or 0) or False,
                    'hr_companions': hr_companions or False,
                    # SORTIE
                    'hr_departure_time': hr_departure_time or False,
                    'hr_return_time': hr_return_time or False,
                    'hr_sortie_reason': hr_sortie_reason or False,
                    'hr_sortie_destination': hr_sortie_destination or False,
                    'hr_vehicle_requested': bool(hr_vehicle_requested),
                    'hr_will_return': hr_will_return or 'yes',
                    # CONGE
                    'hr_leave_reason': hr_leave_reason or False,
                    'hr_replacement_name': hr_replacement_name or False,
                }
                vals.update(self._hr_extra_ticket_vals(selected_type, form_data, kw))

                try:
                    ticket = request.env['assistance.ticket'].sudo().create(vals)
                    ticket.sudo().message_subscribe(
                        partner_ids=[request.env.user.partner_id.id]
                    )
                    ticket.sudo().message_post(
                        body=Markup(
                            'Demande RH « <b>%(type)s</b> » soumise depuis le portail'
                            ' par <b>%(user)s</b>.'
                        ) % {
                            'type': escape(selected_type.name if selected_type else '?'),
                            'user': escape(request.env.user.name),
                        },
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                    # To-Do pour les responsables d'équipe
                    if preselected_team and preselected_team.manager_ids:
                        todo_type = request.env.ref(
                            'mail.mail_activity_data_todo', raise_if_not_found=False
                        )
                        if todo_type:
                            note = Markup(
                                '<p>Demande RH <b>%(type)s</b> reçue de <b>%(user)s</b>.</p>'
                                '<p>Sujet : <b>%(subject)s</b></p>'
                            ) % {
                                'type': escape(selected_type.name if selected_type else '?'),
                                'user': escape(request.env.user.name),
                                'subject': escape(ticket.name),
                            }
                            for manager in preselected_team.manager_ids:
                                ticket.sudo().activity_schedule(
                                    activity_type_id=todo_type.id,
                                    summary=_('Traiter : %s') % ticket.name,
                                    note=note,
                                    user_id=manager.id,
                                )
                    _logger.info(
                        'HR request %s (type=%s) created by %s',
                        ticket.ticket_ref,
                        selected_type.code if selected_type else '?',
                        request.env.user.login,
                    )
                    return request.redirect('/my/assistance/%d?new=1' % ticket.id)

                except Exception as e:
                    _logger.error('HR request creation error: %s', e)
                    error = 'server'

            # POST avec erreur : re-afficher le formulaire
            form_data['name'] = name or ''
            values = self._prepare_portal_layout_values()
            values.update(self._hr_form_values(
                preselected_team, team_request_types, selected_type,
                form_data, error,
            ))
            return request.render('hr_dz_requests.portal_hr_request_form', values)

        # ---- GET avec type sélectionné → formulaire ----
        values = self._prepare_portal_layout_values()
        values.update(self._hr_form_values(
            preselected_team, team_request_types, selected_type, {}, '',
        ))
        return request.render('hr_dz_requests.portal_hr_request_form', values)

    # ------------------------------------------------------------------
    # Route impression ordre de mission — génère le PDF en sudo
    # La route /report/pdf/ standard utilise les droits de l'utilisateur ;
    # hr.employee bloque les champs sensibles pour les portails → 403.
    # On passe par une route dédiée qui vérifie l'accès puis imprime en sudo.
    # ------------------------------------------------------------------

    @http.route('/my/hr_request/<int:ticket_id>/mission_order.pdf',
                type='http', auth='user', website=True)
    def portal_mission_order_pdf(self, ticket_id, **kw):
        from odoo.exceptions import AccessError, MissingError
        try:
            ticket_sudo = self._document_check_access(
                'assistance.ticket', ticket_id
            )
        except (AccessError, MissingError):
            return request.redirect('/my/assistance')

        # Vérification : ticket validé RH + type MISSION
        if (not ticket_sudo.sudo().is_hr_request
                or ticket_sudo.sudo().hr_request_type_code != 'MISSION'
                or ticket_sudo.sudo().hr_validation_state != 'hr_validated'):
            return request.redirect('/my/assistance/%d' % ticket_id)

        # Génération PDF en sudo (contourne les restrictions hr.employee)
        report = request.env.ref(
            'hr_dz_requests.report_mission_order'
        ).sudo()
        pdf_content, mime = report._render_qweb_pdf(
            'hr_dz_requests.report_mission_order_document',
            res_ids=[ticket_id],
        )
        filename = 'Ordre_Mission_%s.pdf' % ticket_sudo.sudo().ticket_ref
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 'attachment; filename="%s"' % filename),
            ],
        )

    # ------------------------------------------------------------------
    # Surcharge détail ticket — données employé en sudo pour éviter le 403
    # (hr.employee restreint les champs sensibles aux utilisateurs portail)
    # ------------------------------------------------------------------

    @http.route(['/my/assistance/<int:ticket_id>',
                 '/my/assistance/<int:ticket_id>/<token>'],
                type='http', auth='user', website=True)
    def portal_assistance_detail(self, ticket_id, token=None, **kw):
        response = super().portal_assistance_detail(ticket_id, token=token, **kw)

        # Injecter les données employé/validation calculées en sudo
        # pour éviter le 403 déclenché par hr.employee sur les champs DZ
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is not None:
            ticket = qcontext.get('ticket')
            if ticket:
                try:
                    t = ticket.sudo()
                    emp = t.hr_employee_id
                    qcontext['hr_emp_name']       = emp.name if emp else ''
                    qcontext['hr_emp_job']        = emp.job_id.name if emp and emp.job_id else ''
                    qcontext['hr_emp_dept']       = emp.department_id.name if emp and emp.department_id else ''
                    qcontext['hr_emp_manager']    = emp.parent_id.name if emp and emp.parent_id else ''
                    qcontext['hr_manager_name']   = t.hr_manager_id.name if t.hr_manager_id else ''
                    qcontext['hr_validated_name'] = t.hr_validated_by.name if t.hr_validated_by else ''
                    qcontext['hr_validation_state']        = t.hr_validation_state
                    qcontext['hr_request_type_code']       = t.hr_request_type_code or ''
                    qcontext['hr_is_request']              = t.is_hr_request
                    qcontext['hr_manager_decision_date']   = t.hr_manager_decision_date
                    qcontext['hr_validation_date']         = t.hr_validation_date
                except Exception:
                    pass

        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hr_form_values(self, team, team_request_types, selected_type,
                        form_data, error):
        values = {
            'preselected_team': team,
            'team_request_types': team_request_types,
            'selected_type': selected_type,
            'page_name': 'assistance_new',
            'error': error,
            'form_data': form_data,
            'transport_labels': TRANSPORT_LABELS,
            'sortie_reason_labels': SORTIE_REASON_LABELS,
        }
        values.update(self._hr_extra_template_values(selected_type))
        return values

    # ------------------------------------------------------------------
    # Hooks d'extension pour les modules enfants (ex: hr_dz_loan)
    # ------------------------------------------------------------------

    def _hr_extra_form_data(self, kw):
        """Données supplémentaires pour form_data (re-population formulaire)."""
        return {}

    def _hr_extra_ticket_vals(self, selected_type, form_data, kw):
        """Valeurs supplémentaires à écrire sur le ticket lors de la création."""
        return {}

    def _hr_extra_template_values(self, selected_type):
        """Variables supplémentaires à injecter dans le template du formulaire."""
        return {}

    def _hr_validate_form(self, selected_type, form_data):
        """Retourne le code d'erreur ou '' si OK."""
        if not selected_type:
            return 'type'
        code = selected_type.code
        if code == 'MISSION':
            if not form_data.get('hr_destination', '').strip():
                return 'destination'
            if not form_data.get('date_start') or not form_data.get('date_end'):
                return 'dates'
        elif code == 'SORTIE':
            if not form_data.get('date_start'):
                return 'date'
            if not form_data.get('hr_departure_time', '').strip():
                return 'departure_time'
        elif code == 'CONGE':
            if not form_data.get('date_start') or not form_data.get('date_end'):
                return 'dates'
        return ''

    def _hr_auto_subject(self, selected_type, form_data):
        """Génère un sujet automatique si l'utilisateur n'en a pas fourni."""
        today = str(fields.Date.today())
        code = selected_type.code if selected_type else ''
        if code == 'MISSION':
            dest = form_data.get('hr_destination') or '?'
            ds = form_data.get('date_start') or today
            return 'Ordre de mission — %s — %s' % (dest, ds)
        elif code == 'SORTIE':
            ds = form_data.get('date_start') or today
            reason = SORTIE_REASON_LABELS.get(
                form_data.get('hr_sortie_reason', ''), ''
            )
            return ('Bon de sortie — %s%s' % (ds, ' (%s)' % reason if reason else ''))
        elif code == 'CONGE':
            ds = form_data.get('date_start') or '?'
            de = form_data.get('date_end') or '?'
            return 'Demande de congé — %s au %s' % (ds, de)
        return selected_type.name if selected_type else 'Demande RH'
