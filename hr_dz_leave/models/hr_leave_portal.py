import logging
from markupsafe import Markup, escape

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    """
    Étend hr.leave pour lier un congé à une demande RH portail.

    Flux :
      RH sélectionne la demande (assistance.ticket) dans le formulaire congé
      → le ticket est mis à jour automatiquement (ticket.hr_leave_id = self)
      → quand le congé est validé, le Titre de congé peut être imprimé
    """
    _inherit = 'hr.leave'

    ticket_id = fields.Many2one(
        'assistance.ticket',
        string='Demande RH (portail)',
        ondelete='set null',
        domain="[('hr_request_type_code', '=', 'CONGE'), ('hr_leave_id', '=', False)]",
        help='Demande de congé soumise depuis le portail liée à ce congé',
        tracking=True,
    )

    # Champs de validation (non présents nativement sur hr.leave en Odoo 19)
    date_validation = fields.Datetime(
        string='Date de validation',
        readonly=True,
        copy=False,
    )
    validated_by = fields.Many2one(
        'hr.employee',
        string='Validé par',
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # Synchronisation bidirectionnelle : quand ticket_id change,
    # mettre à jour ticket.hr_leave_id en retour
    # Capture aussi date_validation / validated_by lors du passage à 'validate'
    # ------------------------------------------------------------------

    def write(self, vals):
        # Mémoriser les anciens liens avant écriture
        old_links = {leave.id: leave.ticket_id for leave in self}
        # Mémoriser les congés qui n'étaient pas encore validés
        not_yet_validated = self.filtered(lambda l: l.state != 'validate')
        res = super().write(vals)

        # Capturer date et validateur lors du passage à l'état 'validate'
        if vals.get('state') == 'validate' and not self.env.context.get('_skip_validation_capture'):
            now = fields.Datetime.now()
            for leave in not_yet_validated.filtered(lambda l: l.state == 'validate'):
                approver = leave.second_approver_id or leave.first_approver_id
                leave.with_context(_skip_validation_capture=True).sudo().write({
                    'date_validation': now,
                    'validated_by': approver.id if approver else False,
                })

        if 'ticket_id' in vals:
            for leave in self:
                old_ticket = old_links.get(leave.id)
                # Effacer l'ancien lien si le ticket a changé
                if old_ticket and old_ticket != leave.ticket_id:
                    try:
                        old_ticket.sudo().write({'hr_leave_id': False})
                    except Exception as e:
                        _logger.warning('Could not clear hr_leave_id on ticket %s: %s',
                                        old_ticket.id, e)
                # Établir le nouveau lien
                if leave.ticket_id:
                    try:
                        leave.ticket_id.sudo().write({'hr_leave_id': leave.id})
                        leave.ticket_id.sudo().message_post(
                            body=Markup(
                                'Congé <b>%(ref)s</b> lié à cette demande par <b>%(user)s</b>.'
                            ) % {
                                'ref': escape(leave.name or str(leave.id)),
                                'user': escape(self.env.user.name),
                            },
                            subtype_xmlid='mail.mt_note',
                        )
                    except Exception as e:
                        _logger.warning('Could not set hr_leave_id on ticket %s: %s',
                                        leave.ticket_id.id, e)
        return res

    def unlink(self):
        # Effacer le lien dans le ticket avant suppression du congé
        for leave in self:
            if leave.ticket_id:
                try:
                    leave.ticket_id.sudo().write({'hr_leave_id': False})
                except Exception as e:
                    _logger.warning('Could not clear hr_leave_id on ticket %s: %s',
                                    leave.ticket_id.id, e)
        return super().unlink()

    def action_print_leave_certificate(self):
        """Imprimer le Titre de congé (disponible après validation)."""
        self.ensure_one()
        return self.env.ref(
            'hr_dz_leave.report_leave_certificate'
        ).report_action(self)
