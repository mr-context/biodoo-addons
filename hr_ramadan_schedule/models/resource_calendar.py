import logging
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    is_ramadan = fields.Boolean(
        string='Mode Ramadan',
        default=False,
        help="Activer pour appliquer des horaires réduits durant le Ramadan. "
             "Les horaires originaux sont conservés et restaurés au toggle OFF. "
             "Configurer via le bouton 'Configurer les horaires'.",
    )
    ramadan_mode = fields.Selection(
        [
            ('uniform', 'Uniforme'),
            ('gender', 'Par genre'),
        ],
        string='Répartition Ramadan',
        default='uniform',
    )

    # ── Uniforme / Hommes ─────────────────────────────────────────────────
    ramadan_hour_from = fields.Float(
        string='Début Ramadan (H)',
        digits=(4, 2),
        help="Heure de début en Ramadan pour tous (uniforme) ou pour les hommes (par genre). "
             "Laisser à 00:00 pour conserver l'heure de début originale de chaque ligne.",
    )
    ramadan_hour_to = fields.Float(
        string='Fin Ramadan (H)',
        digits=(4, 2),
        help="Heure de fin en Ramadan pour tous (uniforme) ou pour les hommes (par genre).",
    )

    # ── Femmes (mode par genre uniquement) ────────────────────────────────
    ramadan_hour_from_female = fields.Float(
        string='Début Ramadan (F)',
        digits=(4, 2),
        help="Heure de début en Ramadan pour les femmes. "
             "Laisser à 00:00 pour utiliser la même heure que les hommes.",
    )
    ramadan_hour_to_female = fields.Float(
        string='Fin Ramadan (F)',
        digits=(4, 2),
        help="Heure de fin en Ramadan pour les femmes.",
    )

    # ── Notification ──────────────────────────────────────────────────────
    ramadan_notify_user_ids = fields.Many2many(
        'res.users',
        'resource_calendar_ramadan_notify_rel',
        'calendar_id',
        'user_id',
        string='Destinataires notifications Ramadan',
        help="Utilisateurs qui recevront l'email d'activation et le rappel de fin de Ramadan.",
    )
    ramadan_start_date = fields.Date(
        string='Date d\'activation Ramadan',
        help="Date à laquelle le mode Ramadan a été activé. "
             "Utilisée pour calculer le rappel de fin (J+26).",
    )
    ramadan_reminder_sent = fields.Boolean(
        string='Rappel fin Ramadan envoyé',
        default=False,
        copy=False,
    )

    @api.constrains(
        'ramadan_hour_from', 'ramadan_hour_to',
        'ramadan_hour_from_female', 'ramadan_hour_to_female',
    )
    def _check_ramadan_hours(self):
        for cal in self:
            for fname, label in [
                ('ramadan_hour_from', 'Début (H)'),
                ('ramadan_hour_to', 'Fin (H)'),
                ('ramadan_hour_from_female', 'Début (F)'),
                ('ramadan_hour_to_female', 'Fin (F)'),
            ]:
                val = getattr(cal, fname)
                if val and (val < 0.0 or val > 24.0):
                    raise ValidationError(
                        _('Heure Ramadan %s doit être comprise entre 0 et 24.') % label
                    )
            if (cal.ramadan_hour_to
                    and cal.ramadan_hour_from
                    and cal.ramadan_hour_to <= cal.ramadan_hour_from):
                raise ValidationError(
                    _('L\'heure de fin Ramadan doit être postérieure à l\'heure de début.')
                )

    # ── Application / Restauration des lignes ─────────────────────────────

    def _restore_lines_from_ramadan(self):
        """Restaure les heures originales depuis le backup sur toutes les lignes."""
        for line in self.attendance_ids:
            if line.original_hour_to:
                line.hour_from = line.original_hour_from
                line.hour_to = line.original_hour_to
                line.original_hour_from = 0.0
                line.original_hour_to = 0.0

    def write(self, vals):
        """Restaure les lignes quand is_ramadan passe de True à False."""
        if 'is_ramadan' in vals and not vals['is_ramadan']:
            for cal in self:
                if cal.is_ramadan:
                    cal._restore_lines_from_ramadan()
            # Remettre à zéro le flag de rappel pour la prochaine activation
            vals = dict(vals, ramadan_reminder_sent=False)
        return super().write(vals)

    # ── Wizard ────────────────────────────────────────────────────────────

    def action_open_ramadan_wizard(self):
        """Ouvre le wizard de configuration des horaires Ramadan."""
        self.ensure_one()
        # Pré-remplir les destinataires : utilisateurs RH managers déjà sélectionnés
        # ou par défaut tous les RH managers
        if self.ramadan_notify_user_ids:
            default_notify_ids = self.ramadan_notify_user_ids.ids
        else:
            group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
            if group:
                default_notify_ids = self.env['res.users'].search([
                    ('group_ids', 'in', [group.id]),
                    ('active', '=', True),
                ]).ids
            else:
                default_notify_ids = []

        return {
            'type': 'ir.actions.act_window',
            'name': 'Configuration des horaires Ramadan',
            'res_model': 'hr.ramadan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_calendar_id': self.id,
                'default_mode': self.ramadan_mode or 'uniform',
                'default_hour_from': self.ramadan_hour_from,
                'default_hour_to': self.ramadan_hour_to,
                'default_hour_from_female': self.ramadan_hour_from_female,
                'default_hour_to_female': self.ramadan_hour_to_female,
                'default_notify_user_ids': [(6, 0, default_notify_ids)],
            },
        }

    # ── Notifications ─────────────────────────────────────────────────────

    def _send_ramadan_email(self, subject, body):
        """Envoie un email aux destinataires configurés sur ce calendrier."""
        emails = self.ramadan_notify_user_ids.filtered('email').mapped('email')
        if not emails:
            _logger.info(
                'Ramadan email skipped for calendar %s: no recipients configured.',
                self.name,
            )
            return
        mail = self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_to': ','.join(emails),
        })
        mail.send()
        _logger.info('Ramadan email "%s" sent for calendar %s to: %s',
                     subject, self.name, ','.join(emails))

    def _notify_ramadan_activated(self):
        """Email d'activation : mode Ramadan activé."""
        body = (
            '<p>Bonjour,</p>'
            '<p>Le mode Ramadan a été activé pour le calendrier de travail '
            f'<strong>{self.name}</strong> à compter du '
            f'<strong>{self.ramadan_start_date}</strong>.</p>'
            '<p><strong>Rappel important :</strong> pensez à '
            '<strong>désactiver le mode Ramadan</strong> '
            'à la fin du mois de Ramadan pour restaurer les horaires normaux.</p>'
            '<p>Un rappel automatique vous sera envoyé 3 à 4 jours avant la fin estimée.</p>'
            '<p>Chemin : Configuration → Horaires de travail → '
            f'<em>{self.name}</em> → désactiver le toggle <em>Mode Ramadan</em>.</p>'
        )
        self._send_ramadan_email(
            subject=f'[Ramadan] Mode Ramadan activé — {self.name}',
            body=body,
        )

    def _notify_ramadan_ending_soon(self):
        """Email de rappel : Ramadan se termine bientôt."""
        body = (
            '<p>Bonjour,</p>'
            '<p>Le mois de Ramadan approche de sa fin.</p>'
            '<p>Pensez à <strong>désactiver le mode Ramadan</strong> '
            f'sur le calendrier <strong>{self.name}</strong> '
            'pour restaurer les horaires normaux dès la fin du mois.</p>'
            '<p>Chemin : Configuration → Horaires de travail → '
            f'<em>{self.name}</em> → désactiver le toggle <em>Mode Ramadan</em>.</p>'
        )
        self._send_ramadan_email(
            subject=f'[Ramadan] Rappel — fin du Ramadan approche — {self.name}',
            body=body,
        )

    # ── Cron ──────────────────────────────────────────────────────────────

    @api.model
    def _cron_ramadan_reminder(self):
        """Cron journalier : envoie un rappel de fin de Ramadan à J+26.

        Ramadan dure 29 ou 30 jours.
        J+26 = 3 jours avant la fin d'un Ramadan de 29 jours
               4 jours avant la fin d'un Ramadan de 30 jours.
        """
        # Envoyer le rappel entre J+24 et J+28 (tolérance si le cron a sauté un jour)
        # et uniquement si le rappel n'a pas encore été envoyé pour ce calendrier.
        today = date.today()
        date_min = today - timedelta(days=28)
        date_max = today - timedelta(days=24)

        calendars = self.search([
            ('is_ramadan', '=', True),
            ('ramadan_start_date', '>=', date_min),
            ('ramadan_start_date', '<=', date_max),
            ('ramadan_reminder_sent', '=', False),
        ])
        for cal in calendars:
            _logger.info('Sending Ramadan ending-soon reminder for calendar %s', cal.name)
            cal._notify_ramadan_ending_soon()
            cal.ramadan_reminder_sent = True
