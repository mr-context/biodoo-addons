import logging
from datetime import datetime, time

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AssistanceTicket(models.Model):
    _inherit = 'assistance.ticket'

    # ------------------------------------------------------------------
    # Identification commune
    # ------------------------------------------------------------------
    hr_request_type_id = fields.Many2one(
        'hr.request.type',
        string='Type de demande RH',
        ondelete='set null',
        index=True,
        tracking=True,
    )
    # Champ stocké pour les conditions invisible= dans les vues
    hr_request_type_code = fields.Char(
        related='hr_request_type_id.code',
        store=True,
        readonly=True,
        string='Code type RH',
    )
    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Employé demandeur',
        ondelete='set null',
        tracking=True,
    )
    is_hr_request = fields.Boolean(
        string='Demande RH',
        compute='_compute_is_hr_request',
        store=True,
    )

    # ------------------------------------------------------------------
    # Champs partagés (dates)
    # ------------------------------------------------------------------
    hr_date_start = fields.Date(string='Date début')
    hr_date_end = fields.Date(string='Date fin')

    # ------------------------------------------------------------------
    # ORDRE DE MISSION
    # ------------------------------------------------------------------
    hr_mission_object = fields.Text(
        string='Objet de la mission',
        help='But et contexte du déplacement',
    )
    hr_destination = fields.Char(
        string='Destination',
        help='Ville, wilaya ou pays de destination',
    )
    hr_transport_mode = fields.Selection([
        ('car_service',  'Véhicule de service'),
        ('car_personal', 'Véhicule personnel'),
        ('train',        'Train'),
        ('plane',        'Avion'),
        ('taxi',         'Taxi / Transport en commun'),
        ('other',        'Autre'),
    ], string='Moyen de transport')
    hr_advance_amount = fields.Float(
        string='Avance sur frais (DA)',
        digits=(15, 2),
        help='Montant d\'avance demandé pour couvrir les frais de mission',
    )
    hr_companions = fields.Text(
        string='Accompagnateurs',
        help='Noms et postes des personnes participant à la mission',
    )

    # ------------------------------------------------------------------
    # BON DE SORTIE
    # ------------------------------------------------------------------
    hr_departure_time = fields.Char(
        string='Heure de départ',
        help='Format HH:MM — ex : 09:30',
    )
    hr_return_time = fields.Char(
        string='Heure de retour prévue',
        help='Format HH:MM — ex : 15:00',
    )
    hr_sortie_reason = fields.Selection([
        ('service',        'Raison de service'),
        ('administrative', 'Démarche administrative'),
        ('medical',        'Rendez-vous médical'),
        ('personal',       'Motif personnel'),
        ('other',          'Autre'),
    ], string='Motif de sortie')
    hr_sortie_destination = fields.Char(string='Lieu / Destination')
    hr_vehicle_requested = fields.Boolean(
        string='Véhicule de service demandé',
        default=False,
    )
    hr_will_return = fields.Selection([
        ('yes', 'Oui — retour au poste'),
        ('no',  'Non — absence jusqu\'à la fin de journée'),
    ], string='Retour au poste prévu',
       default='yes',
       help='Indique si l\'employé prévoit de regagner son poste après la sortie',
    )

    # ------------------------------------------------------------------
    # DEMANDE DE CONGÉ
    # ------------------------------------------------------------------
    hr_leave_reason = fields.Char(
        string='Motif / Événement',
        help='Précisez pour un congé exceptionnel (mariage, décès, naissance…)',
    )
    hr_replacement_name = fields.Char(
        string='Remplaçant(e)',
        help='Nom de la personne assurant la continuité pendant l\'absence',
    )
    hr_days_count = fields.Float(
        string='Nombre de jours',
        compute='_compute_hr_days_count',
        store=True,
        readonly=True,
    )
    # Lien vers le hr.leave créé automatiquement à la validation RH
    hr_leave_id = fields.Many2one(
        'hr.leave',
        string='Congé associé',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    # Allocation choisie par le RH — détermine sur quelle année imputer
    hr_allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Imputer sur (année)',
        copy=False,
        domain="[('employee_id', '=', hr_employee_id), ('state', '=', 'validate'), ('number_of_days', '>', 0)]",
        help='Allocation annuelle sur laquelle seront imputés les jours de congé',
    )
    # Solde restant lu depuis l'allocation choisie
    hr_leave_balance = fields.Float(
        string='Solde disponible (jours)',
        compute='_compute_hr_leave_balance',
        help='Solde de congé restant de l\'employé pour l\'allocation sélectionnée',
    )
    # Allocations disponibles (pour affichage tableau dans la vue)
    hr_allocation_ids = fields.One2many(
        'hr.leave.allocation',
        compute='_compute_hr_allocation_ids',
        string='Allocations disponibles',
    )

    # ------------------------------------------------------------------
    # Commentaire commun (tous types)
    # ------------------------------------------------------------------
    hr_justification = fields.Text(
        string='Commentaire additionnel',
        help='Informations complémentaires à destination du service RH',
    )

    # ------------------------------------------------------------------
    # WORKFLOW DE VALIDATION
    # ------------------------------------------------------------------
    hr_validation_state = fields.Selection([
        ('draft',            'Brouillon'),
        ('manager_pending',  'En attente — responsable'),
        ('manager_approved', 'Approuvé — responsable'),
        ('manager_refused',  'Refusé — responsable'),
        ('hr_validated',     'Validé RH'),
        ('hr_refused',       'Refusé RH'),
    ], string='État de validation',
       default='draft',
       copy=False,
       help='Workflow de validation à deux niveaux : responsable hiérarchique puis RH',
    )
    hr_manager_id = fields.Many2one(
        'res.users',
        string='Responsable hiérarchique',
        compute='_compute_hr_manager',
        store=True,
        help='Déduit automatiquement depuis la fiche employé (parent_id)',
    )
    hr_manager_note = fields.Text(string='Note du responsable')
    hr_manager_decision_date = fields.Datetime(
        string='Date de décision — responsable',
        readonly=True,
        copy=False,
    )
    hr_validation_date = fields.Datetime(
        string='Date de validation RH',
        readonly=True,
        copy=False,
    )
    hr_validated_by = fields.Many2one(
        'res.users',
        string='Validé par (RH)',
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('hr_request_type_id')
    def _compute_is_hr_request(self):
        for ticket in self:
            ticket.is_hr_request = bool(ticket.hr_request_type_id)

    @api.depends('hr_allocation_id', 'hr_employee_id', 'hr_request_type_id')
    def _compute_hr_leave_balance(self):
        for ticket in self:
            if ticket.hr_allocation_id:
                ticket.hr_leave_balance = ticket.hr_allocation_id.number_of_days - ticket.hr_allocation_id.leaves_taken
            elif (ticket.hr_employee_id and ticket.hr_request_type_id
                  and ticket.hr_request_type_id.leave_type_id):
                try:
                    leave_type = ticket.hr_request_type_id.leave_type_id.with_context(
                        employee_id=ticket.hr_employee_id.id
                    )
                    ticket.hr_leave_balance = leave_type.virtual_remaining_leaves or 0.0
                except Exception:
                    ticket.hr_leave_balance = 0.0
            else:
                ticket.hr_leave_balance = 0.0

    @api.depends('hr_employee_id', 'hr_request_type_id')
    def _compute_hr_allocation_ids(self):
        for ticket in self:
            if not ticket.hr_employee_id or not ticket.hr_request_type_id or not ticket.hr_request_type_id.leave_type_id:
                ticket.hr_allocation_ids = self.env['hr.leave.allocation']
                continue
            ticket.hr_allocation_ids = self.env['hr.leave.allocation'].search([
                ('employee_id', '=', ticket.hr_employee_id.id),
                ('holiday_status_id', '=', ticket.hr_request_type_id.leave_type_id.id),
                ('state', '=', 'validate'),
            ], order='date_from asc')

    @api.depends('hr_date_start', 'hr_date_end')
    def _compute_hr_days_count(self):
        for ticket in self:
            if ticket.hr_date_start and ticket.hr_date_end:
                delta = (ticket.hr_date_end - ticket.hr_date_start).days + 1
                ticket.hr_days_count = max(0.0, float(delta))
            else:
                ticket.hr_days_count = 0.0

    @api.depends('hr_employee_id', 'hr_employee_id.parent_id',
                 'hr_employee_id.parent_id.user_id')
    def _compute_hr_manager(self):
        for ticket in self:
            emp = ticket.hr_employee_id
            if emp and emp.parent_id and emp.parent_id.user_id:
                ticket.hr_manager_id = emp.parent_id.user_id
            else:
                ticket.hr_manager_id = False

    # ------------------------------------------------------------------
    # Actions de validation
    # ------------------------------------------------------------------

    def action_send_to_manager(self):
        """Soumet la demande au responsable hiérarchique pour approbation.

        Si le responsable n'a pas de compte Odoo → passage direct à
        manager_approved avec notification à l'équipe RH (fallback).
        """
        self.ensure_one()
        if not self.is_hr_request:
            return

        todo_type = self.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False
        )

        if self.hr_manager_id:
            # Cas normal : responsable avec compte Odoo
            self.hr_validation_state = 'manager_pending'
            if todo_type:
                self.activity_schedule(
                    activity_type_id=todo_type.id,
                    summary=_('Demande RH à approuver : %s') % self.name,
                    note=Markup(
                        '<p>L\'employé <b>%(emp)s</b> a soumis une demande '
                        '<b>%(type)s</b> : <b>%(name)s</b>.</p>'
                        '<p>Merci de valider ou refuser depuis le ticket.</p>'
                    ) % {
                        'emp': escape(self.hr_employee_id.name if self.hr_employee_id else '?'),
                        'type': escape(self.hr_request_type_id.name if self.hr_request_type_id else '?'),
                        'name': escape(self.name),
                    },
                    user_id=self.hr_manager_id.id,
                )
            self.message_post(
                body=Markup('Demande envoyée à <b>%s</b> pour approbation.')
                     % escape(self.hr_manager_id.name),
                subtype_xmlid='mail.mt_note',
            )

        else:
            # Fallback : aucun responsable hiérarchique — validation RH directe
            self.hr_validation_state = 'manager_approved'
            self.message_post(
                body=Markup(
                    'Aucun responsable hiérarchique trouvé. '
                    'La demande est transmise directement à l\'équipe RH pour validation.'
                ),
                subtype_xmlid='mail.mt_note',
            )
            if self.team_id and self.team_id.manager_ids and todo_type:
                note = Markup(
                    '<p>Demande <b>%(type)s</b> de <b>%(emp)s</b> : <b>%(name)s</b>.</p>'
                    '<p>Aucun responsable hiérarchique — validation RH directe requise.</p>'
                ) % {
                    'type': escape(self.hr_request_type_id.name if self.hr_request_type_id else '?'),
                    'emp': escape(self.hr_employee_id.name if self.hr_employee_id else '?'),
                    'name': escape(self.name),
                }
                for manager in self.team_id.manager_ids:
                    self.activity_schedule(
                        activity_type_id=todo_type.id,
                        summary=_('Validation RH directe : %s') % self.name,
                        note=note,
                        user_id=manager.id,
                    )

    def action_manager_approve(self):
        """Le responsable hiérarchique approuve la demande."""
        self.ensure_one()
        self.write({
            'hr_validation_state': 'manager_approved',
            'hr_manager_decision_date': fields.Datetime.now(),
        })
        self.message_post(
            body=Markup(
                '<b>%s</b> (responsable hiérarchique) a approuvé la demande. '
                'En attente de validation RH.'
            ) % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )
        # Marquer l'activité du responsable comme terminée
        try:
            self.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Demande approuvée.'),
            )
        except Exception:
            pass

        # Notifier l'équipe RH
        todo_type = self.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False
        )
        if self.team_id and self.team_id.manager_ids and todo_type:
            note = Markup(
                '<p>Le responsable <b>%(mgr)s</b> a approuvé la demande '
                '<b>%(name)s</b> de <b>%(emp)s</b>.</p>'
                '<p>Merci de procéder à la validation RH.</p>'
            ) % {
                'mgr': escape(self.env.user.name),
                'name': escape(self.name),
                'emp': escape(self.hr_employee_id.name if self.hr_employee_id else '?'),
            }
            for manager in self.team_id.manager_ids:
                self.activity_schedule(
                    activity_type_id=todo_type.id,
                    summary=_('Validation RH : %s') % self.name,
                    note=note,
                    user_id=manager.id,
                )

    def action_manager_refuse(self):
        """Le responsable hiérarchique refuse la demande."""
        self.ensure_one()
        self.write({
            'hr_validation_state': 'manager_refused',
            'hr_manager_decision_date': fields.Datetime.now(),
        })
        self.message_post(
            body=Markup('<b>%s</b> (responsable hiérarchique) a refusé la demande.')
                 % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )
        try:
            self.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Demande refusée.'),
            )
        except Exception:
            pass

    def action_hr_validate(self):
        """L'équipe RH valide définitivement la demande."""
        self.ensure_one()

        # --- Création automatique du congé pour les demandes CONGE ---
        if (self.hr_request_type_id and self.hr_request_type_id.creates_hr_leave
                and self.hr_request_type_id.leave_type_id
                and not self.hr_leave_id):
            self._create_leave_from_ticket()

        self.write({
            'hr_validation_state': 'hr_validated',
            'hr_validation_date': fields.Datetime.now(),
            'hr_validated_by': self.env.user.id,
        })
        self.message_post(
            body=Markup('<b>%s</b> a validé la demande RH. Le document peut être imprimé.')
                 % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )
        try:
            self.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Demande validée par RH.'),
            )
        except Exception:
            pass

    def _create_leave_from_ticket(self):
        """Crée un hr.leave depuis le ticket et impute sur l'allocation choisie."""
        self.ensure_one()

        if not self.hr_employee_id:
            raise UserError(_('Aucun employé lié à cette demande.'))
        if not self.hr_date_start or not self.hr_date_end:
            raise UserError(_('Les dates de congé sont obligatoires.'))

        alloc = self.hr_allocation_id
        days_needed = self.hr_days_count

        # Vérification du solde si allocation choisie
        if alloc:
            remaining = alloc.number_of_days - alloc.leaves_taken
            if days_needed > remaining:
                raise UserError(_(
                    'Solde insuffisant sur l\'allocation "%s" : '
                    '%s jours demandés, %s jours disponibles.'
                ) % (alloc.name, days_needed, remaining))

        # Création du hr.leave
        leave = self.env['hr.leave'].sudo().create({
            'name': self.name,
            'employee_id': self.hr_employee_id.id,
            'holiday_status_id': self.hr_request_type_id.leave_type_id.id,
            'date_from': datetime.combine(self.hr_date_start, time(7, 0, 0)),
            'date_to': datetime.combine(self.hr_date_end, time(17, 0, 0)),
            'request_date_from': self.hr_date_start,
            'request_date_to': self.hr_date_end,
        })

        # Validation du congé (state → validate)
        try:
            leave.sudo().action_approve()
        except Exception:
            pass
        try:
            leave.sudo().action_validate()
        except Exception:
            pass

        # Forcer l'imputation sur l'allocation choisie
        # Odoo déduit automatiquement en FIFO. Si une allocation spécifique
        # est choisie et différente de celle consommée, on swap manuellement.
        if alloc and leave.state == 'validate':
            auto_alloc = self.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', self.hr_employee_id.id),
                ('holiday_status_id', '=', self.hr_request_type_id.leave_type_id.id),
                ('state', '=', 'validate'),
                ('id', '!=', alloc.id),
                ('leaves_taken', '>', 0),
            ], order='date_from asc', limit=1)

            if auto_alloc and auto_alloc.id != alloc.id:
                # Remettre les jours sur l'allocation auto, déduire de la choisie
                auto_alloc.sudo().write({
                    'number_of_days': auto_alloc.number_of_days + days_needed
                })
                alloc.sudo().write({
                    'number_of_days': alloc.number_of_days - days_needed
                })

        self.hr_leave_id = leave
        self.message_post(
            body=Markup(
                'Congé créé automatiquement : <b>%(leave)s</b>'
                '%(alloc)s'
            ) % {
                'leave': escape(leave.name or ''),
                'alloc': Markup(' — imputé sur <b>%s</b>') % escape(alloc.name)
                         if alloc else '',
            },
            subtype_xmlid='mail.mt_note',
        )

    def action_hr_refuse(self):
        """L'équipe RH refuse la demande."""
        self.ensure_one()
        self.write({
            'hr_validation_state': 'hr_refused',
            'hr_validation_date': fields.Datetime.now(),
            'hr_validated_by': self.env.user.id,
        })
        self.message_post(
            body=Markup('<b>%s</b> (RH) a refusé la demande.')
                 % escape(self.env.user.name),
            subtype_xmlid='mail.mt_comment',
        )
        try:
            self.activity_feedback(
                ['mail.mail_activity_data_todo'],
                feedback=_('Demande refusée par RH.'),
            )
        except Exception:
            pass

    def action_reset_to_draft(self):
        """Remettre en brouillon (correction avant re-soumission)."""
        self.ensure_one()
        self.write({'hr_validation_state': 'draft'})
        self.message_post(
            body=_('Demande remise en brouillon.'),
            subtype_xmlid='mail.mt_note',
        )

    def action_print_mission_order(self):
        """Imprimer l'ordre de mission (disponible après validation RH)."""
        self.ensure_one()
        return self.env.ref(
            'hr_dz_requests.report_mission_order'
        ).report_action(self)

    def action_print_bon_sortie(self):
        """Imprimer le bon de sortie (disponible après validation RH)."""
        self.ensure_one()
        return self.env.ref(
            'hr_dz_requests.report_bon_sortie'
        ).report_action(self)

