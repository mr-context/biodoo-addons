import logging

from odoo import fields, http, _
from odoo.http import request
from odoo.exceptions import AccessError, MissingError
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class AssistancePortal(CustomerPortal):
    """Routes portail pour le module assistance."""

    # ------------------------------------------------------------------
    # Compteur page d'accueil
    # ------------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'assistance_count' in counters:
            values['assistance_count'] = request.env['assistance.ticket'].sudo().search_count(
                self._assistance_get_domain()
            )
        return values

    def _assistance_get_domain(self):
        return [('partner_id', '=', request.env.user.partner_id.id)]

    # ------------------------------------------------------------------
    # /my/assistance — liste
    # ------------------------------------------------------------------

    @http.route(['/my/assistance', '/my/assistance/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_assistance(self, page=1, search=None, filterby='open', sortby='newest',
                             tab='topics', **kw):
        # Équipes portail (topics) pour les cartes de sélection
        portal_teams = request.env['assistance.team'].sudo().search(
            [('privacy_visibility', '=', 'portal')]
        )

        # Si aucune équipe portail, on atterrit directement sur la liste
        if not portal_teams and tab == 'topics':
            tab = 'list'

        searchbar_filters = {
            'all':    {'label': _('Tout'), 'domain': []},
            'open':   {'label': _('Ouverts'), 'domain': [('close_date', '=', False)]},
            'closed': {'label': _('Résolus'), 'domain': [('close_date', '!=', False)]},
        }
        searchbar_sortings = {
            'newest':  {'label': _('Plus récent'), 'order': 'id desc'},
            'subject': {'label': _('Sujet'), 'order': 'name'},
        }

        # Charger les tickets seulement si on est sur l'onglet liste
        tickets = request.env['assistance.ticket'].sudo().browse()
        pager = {}
        total = 0

        if tab == 'list':
            Ticket = request.env['assistance.ticket'].sudo()
            domain = self._assistance_get_domain()

            if filterby not in searchbar_filters:
                filterby = 'open'
            domain += searchbar_filters[filterby]['domain']

            if sortby not in searchbar_sortings:
                sortby = 'newest'
            order = searchbar_sortings[sortby]['order']

            if search:
                domain += ['|', ('name', 'ilike', search), ('ticket_ref', 'ilike', search)]

            total = Ticket.search_count(domain)
            pager = portal_pager(
                url='/my/assistance',
                url_args={'filterby': filterby, 'sortby': sortby,
                          'search': search or '', 'tab': 'list'},
                total=total,
                page=page,
                step=self._items_per_page,
            )
            tickets = Ticket.search(domain, order=order,
                                    limit=self._items_per_page, offset=pager['offset'])
        else:
            filterby = filterby if filterby in searchbar_filters else 'open'
            sortby = sortby if sortby in searchbar_sortings else 'newest'

        # Compteur total des tickets (pour le badge "Mes demandes")
        ticket_count = request.env['assistance.ticket'].sudo().search_count(
            self._assistance_get_domain()
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'portal_teams': portal_teams,
            'tickets': tickets,
            'pager': pager,
            'ticket_count': ticket_count,
            'tab': tab,
            'page_name': 'assistance',
            'searchbar_filters': searchbar_filters,
            'searchbar_sortings': searchbar_sortings,
            'filterby': filterby,
            'sortby': sortby,
            'search': search or '',
            'default_url': '/my/assistance',
        })
        return request.render('assistance.portal_my_assistance', values)

    # ------------------------------------------------------------------
    # /my/assistance/new — formulaire création (GET + POST)
    # ------------------------------------------------------------------

    @http.route('/my/assistance/new', type='http', auth='user', website=True,
                methods=['GET', 'POST'])
    def portal_assistance_new(self, name=None, team_id=None, description=None, **kw):
        teams = request.env['assistance.team'].sudo().search(
            [('privacy_visibility', '=', 'portal')]
        )

        # ---- POST : création du ticket ----
        if request.httprequest.method == 'POST':
            error = ''
            if not name or not name.strip():
                error = 'subject'

            if not error:
                # Équipe
                team = None
                if team_id:
                    try:
                        team = request.env['assistance.team'].sudo().search(
                            [('id', '=', int(team_id)),
                             ('privacy_visibility', '=', 'portal')],
                            limit=1,
                        )
                    except (ValueError, TypeError):
                        pass
                if not team:
                    team = teams[:1]

                # Première étape
                if team:
                    stage = request.env['assistance.stage'].sudo().search(
                        ['|', ('team_ids', 'in', team.ids), ('team_ids', '=', False)],
                        order='sequence, id',
                        limit=1,
                    )
                else:
                    stage = request.env['assistance.stage'].sudo().search(
                        [], order='sequence, id', limit=1
                    )

                # Pas d'auto-assign : le ticket reste non assigné,
                # les responsables reçoivent un To-Do pour l'assigner
                user_id = False

                vals = {
                    'name': name.strip(),
                    'partner_id': request.env.user.partner_id.id,
                    'team_id': team.id if team else False,
                    'stage_id': stage.id if stage else False,
                    'user_id': user_id,
                    'description': description or '',
                }

                try:
                    ticket = request.env['assistance.ticket'].sudo().create(vals)
                    # Abonner le demandeur pour qu'il reçoive les notifications
                    ticket.sudo().message_subscribe(
                        partner_ids=[request.env.user.partner_id.id]
                    )
                    # Message dans le chatter
                    ticket.sudo().message_post(
                        body=_('Demande créée depuis le portail par <b>%s</b>.') % request.env.user.name,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                    # To-Do pour chaque responsable : assigner le ticket à un agent
                    if team and team.manager_ids:
                        todo_type = request.env.ref(
                            'mail.mail_activity_data_todo', raise_if_not_found=False
                        )
                        if todo_type:
                            note = _(
                                '<p>Nouvelle demande portail soumise par <b>%(user)s</b>.</p>'
                                '<p>Sujet : <b>%(subject)s</b></p>'
                                '<p>Veuillez l\'assigner à un agent de l\'équipe <b>%(team)s</b>.</p>'
                            ) % {
                                'user': request.env.user.name,
                                'subject': ticket.name,
                                'team': team.name,
                            }
                            for manager in team.manager_ids:
                                ticket.sudo().activity_schedule(
                                    activity_type_id=todo_type.id,
                                    summary=_('Assigner ce ticket à un agent'),
                                    note=note,
                                    user_id=manager.id,
                                )
                    _logger.info('Assistance ticket %s created from portal by %s',
                                 ticket.ticket_ref, request.env.user.login)
                    return request.redirect('/my/assistance/%d?new=1' % ticket.id)
                except Exception as e:
                    _logger.error('Error creating assistance ticket from portal: %s', e)
                    error = 'server'

            values = self._prepare_portal_layout_values()
            values.update({
                'teams': teams,
                'page_name': 'assistance_new',
                'error': error,
                'form_data': {'name': name, 'description': description},
            })
            return request.render('assistance.portal_assistance_new', values)

        # ---- GET : affichage du formulaire (team_id pré-sélectionné si passé en URL) ----
        preselected_team = None
        if team_id:
            try:
                preselected_team = request.env['assistance.team'].sudo().search(
                    [('id', '=', int(team_id)),
                     ('privacy_visibility', '=', 'portal')],
                    limit=1,
                )
            except (ValueError, TypeError):
                pass

        values = self._prepare_portal_layout_values()
        values.update({
            'teams': teams,
            'preselected_team': preselected_team,
            'page_name': 'assistance_new',
            'error': '',
            'form_data': {},
        })
        return request.render('assistance.portal_assistance_new', values)

    # ------------------------------------------------------------------
    # /my/assistance/<id> — détail
    # ------------------------------------------------------------------

    @http.route(['/my/assistance/<int:ticket_id>',
                 '/my/assistance/<int:ticket_id>/<token>'],
                type='http', auth='user', website=True)
    def portal_assistance_detail(self, ticket_id, token=None, **kw):
        try:
            ticket_sudo = self._document_check_access('assistance.ticket', ticket_id, token)
        except (AccessError, MissingError):
            _logger.warning('Portal access denied to ticket %d for user %s',
                            ticket_id, request.env.user.login)
            return request.redirect('/my/assistance')

        values = self._prepare_portal_layout_values()
        values.update({
            'ticket': ticket_sudo,
            'page_name': 'assistance_detail',
            'ticket_closed': kw.get('ticket_closed', False),
            'ticket_new': kw.get('new', False),
        })
        return request.render('assistance.portal_assistance_detail', values)

    # ------------------------------------------------------------------
    # /my/assistance/<id>/close — fermeture portail
    # ------------------------------------------------------------------

    @http.route(['/my/assistance/<int:ticket_id>/close',
                 '/my/assistance/<int:ticket_id>/<token>/close'],
                type='http', auth='user', website=True)
    def portal_assistance_close(self, ticket_id, token=None, **kw):
        try:
            ticket_sudo = self._document_check_access('assistance.ticket', ticket_id, token)
        except (AccessError, MissingError):
            return request.redirect('/my/assistance')

        if not ticket_sudo.close_date:
            closed_stage = request.env['assistance.stage'].sudo().search(
                [('is_closed', '=', True)],
                order='sequence, id',
                limit=1,
            )
            ticket_sudo.write({
                'stage_id': closed_stage.id if closed_stage else ticket_sudo.stage_id.id,
                'closed_by_partner': True,
                'close_date': fields.Datetime.now(),
            })
            ticket_sudo.message_post(
                body=_('Demande fermée par le demandeur depuis le portail.'),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                author_id=request.env.user.partner_id.id,
            )

        return request.redirect('/my/assistance/%d?ticket_closed=1' % ticket_id)
