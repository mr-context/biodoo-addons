import logging
from markupsafe import Markup, escape

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AssistanceTicket(models.Model):
    """
    Étend assistance.ticket avec les champs spécifiques au prêt salarial.
    Lors de la validation RH d'un ticket LOAN → création automatique de hr.loan.
    """
    _inherit = 'assistance.ticket'

    # Champs LOAN sur le ticket
    hr_loan_amount = fields.Float(
        string='Montant demandé',
        help='Montant du prêt salarial demandé par l\'employé',
    )
    hr_loan_nb_months = fields.Integer(
        string='Nombre de mensualités souhaitées',
        default=6,
    )
    hr_loan_reason = fields.Text(
        string='Motif de la demande',
    )
    hr_loan_id = fields.Many2one(
        'hr.loan',
        string='Prêt associé',
        readonly=True,
        copy=False,
    )
    hr_loan_amount_per_month = fields.Float(
        string='Mensualité estimée',
        compute='_compute_loan_amount_per_month',
    )
    # Champs reliés à hr.loan pour gestion directe depuis le ticket
    hr_loan_state = fields.Selection(
        related='hr_loan_id.state',
        string='État du prêt',
        readonly=True,
    )
    hr_loan_commitment_signed = fields.Boolean(
        related='hr_loan_id.commitment_signed',
        string='Engagement signé',
        readonly=False,
    )
    hr_loan_bank_check_signed = fields.Boolean(
        related='hr_loan_id.bank_check_signed',
        string='Chèque de banque signé',
        readonly=False,
    )
    hr_loan_bank_check_number = fields.Char(
        related='hr_loan_id.bank_check_number',
        string='N° du chèque de banque',
        readonly=False,
    )
    hr_loan_commitment_date = fields.Date(
        related='hr_loan_id.commitment_date',
        string='Date de signature',
        readonly=False,
    )

    @api.depends('hr_loan_amount', 'hr_loan_nb_months')
    def _compute_loan_amount_per_month(self):
        for ticket in self:
            if ticket.hr_loan_nb_months > 0 and ticket.hr_loan_amount > 0:
                ticket.hr_loan_amount_per_month = round(
                    ticket.hr_loan_amount / ticket.hr_loan_nb_months, 2
                )
            else:
                ticket.hr_loan_amount_per_month = 0.0

    # ------------------------------------------------------------------
    # Override hr_manager : pour LOAN, pas de responsable (RH direct)
    # ------------------------------------------------------------------

    @api.depends('hr_request_type_id', 'hr_employee_id')
    def _compute_hr_manager(self):
        """Pour les tickets LOAN, forcer hr_manager_id à False (RH direct)."""
        super()._compute_hr_manager()
        for ticket in self:
            if ticket.hr_request_type_code == 'LOAN':
                ticket.hr_manager_id = False

    # ------------------------------------------------------------------
    # Création automatique du prêt lors de la validation RH
    # ------------------------------------------------------------------

    def action_hr_validate(self):
        """Override : si ticket LOAN → créer hr.loan après validation."""
        res = super().action_hr_validate()
        for ticket in self:
            if ticket.hr_request_type_code == 'LOAN' and not ticket.hr_loan_id:
                ticket._create_loan_from_ticket()
        return res

    def action_print_loan_commitment(self):
        """Imprime le bon d'engagement depuis le ticket et passe le prêt en pending_sign."""
        self.ensure_one()
        if not self.hr_loan_id:
            return
        return self.hr_loan_id.action_request_sign()

    def action_approve_loan(self):
        """Approuve le prêt depuis le ticket (vérifie les signatures)."""
        self.ensure_one()
        if not self.hr_loan_id:
            return
        self.hr_loan_id.action_approve()

    def _create_loan_from_ticket(self):
        """Crée un hr.loan depuis les données du ticket LOAN."""
        self.ensure_one()
        if not self.hr_employee_id:
            _logger.warning('Ticket LOAN %s : aucun employé, prêt non créé.', self.id)
            return
        if not self.hr_loan_amount or self.hr_loan_amount <= 0:
            _logger.warning('Ticket LOAN %s : montant invalide, prêt non créé.', self.id)
            return

        loan = self.env['hr.loan'].sudo().create({
            'employee_id': self.hr_employee_id.id,
            'amount': self.hr_loan_amount,
            'nb_months': self.hr_loan_nb_months or 6,
            'reason': self.hr_loan_reason or self.name,
            'ticket_id': self.id,
            'date_request': self.create_date.date() if self.create_date else fields.Date.today(),
        })
        # Le prêt reste en brouillon : le RH doit imprimer l'engagement,
        # le faire signer, puis approuver depuis la fiche prêt.

        self.sudo().write({'hr_loan_id': loan.id})
        self.message_post(
            body=Markup(
                'Prêt <b>%(ref)s</b> créé suite à la validation RH — '
                'montant : <b>%(amount).2f DA</b> sur <b>%(nb)d</b> mois. '
                'Imprimer l\'engagement et le faire signer avant approbation.'
            ) % {
                'ref': escape(loan.name),
                'amount': loan.amount,
                'nb': loan.nb_months,
            },
            subtype_xmlid='mail.mt_comment',
        )
