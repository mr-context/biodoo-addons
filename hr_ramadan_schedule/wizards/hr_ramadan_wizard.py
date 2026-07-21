from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrRamadanWizard(models.TransientModel):
    _name = 'hr.ramadan.wizard'
    _description = 'Configuration des horaires Ramadan'

    calendar_id = fields.Many2one(
        'resource.calendar',
        string='Calendrier de travail',
        required=True,
        readonly=True,
    )
    mode = fields.Selection(
        [
            ('uniform', 'Uniforme — même horaire pour tous'),
            ('gender', 'Par genre — hommes et femmes différents'),
        ],
        string='Répartition',
        default='uniform',
        required=True,
    )

    # ── Uniforme / Hommes ─────────────────────────────────────────────────
    hour_from = fields.Float(
        string='Heure de début',
        digits=(4, 2),
        help="Laisser à 00:00 pour conserver l'heure de début originale de chaque "
             "ligne horaire (seule la fin change).",
    )
    hour_to = fields.Float(
        string='Heure de fin',
        digits=(4, 2),
        help="Heure de fin en mode uniforme, ou heure de fin pour les hommes en mode par genre.",
    )

    # ── Femmes (mode par genre uniquement) ────────────────────────────────
    hour_from_female = fields.Float(
        string='Heure de début (femmes)',
        digits=(4, 2),
        help="Laisser à 00:00 pour utiliser la même heure de début que les hommes.",
    )
    hour_to_female = fields.Float(
        string='Heure de fin (femmes)',
        digits=(4, 2),
    )

    # ── Date de début réelle du Ramadan ───────────────────────────────────
    ramadan_date_start = fields.Date(
        string='Date de début du Ramadan',
        required=True,
        default=fields.Date.today,
        help="Date réelle du premier jour du Ramadan. "
             "Le rappel de fin sera envoyé automatiquement à cette date + 26 jours.",
    )

    # ── Destinataires ─────────────────────────────────────────────────────
    notify_user_ids = fields.Many2many(
        'res.users',
        string='Destinataires des notifications',
        help="Recevront l'email d'activation immédiatement et le rappel automatique "
             "à J+26 (3-4 jours avant la fin estimée du Ramadan).",
    )

    # ── Validation ────────────────────────────────────────────────────────

    @api.constrains('hour_to', 'mode', 'hour_to_female')
    def _check_hours(self):
        for rec in self:
            if not rec.hour_to:
                raise ValidationError(
                    "L'heure de fin est obligatoire."
                )
            if rec.mode == 'gender' and not rec.hour_to_female:
                raise ValidationError(
                    "L'heure de fin (femmes) est obligatoire en mode par genre."
                )

    # ── Actions ───────────────────────────────────────────────────────────

    def action_apply(self):
        """Applique les horaires Ramadan sur le calendrier et notifie les RH."""
        self.ensure_one()
        cal = self.calendar_id

        # Stocker la configuration sur le calendrier uniquement.
        # Les lignes du calendrier ne sont PAS modifiées : les heures Ramadan
        # sont lues dynamiquement via getattr dans _fill_scheduled_times et
        # _get_calendar_day_hours, ce qui évite tout recalcul rétroactif
        # des overtime par le moteur natif Odoo.
        cal.write({
            'is_ramadan': True,
            'ramadan_mode': self.mode,
            'ramadan_hour_from': self.hour_from,
            'ramadan_hour_to': self.hour_to,
            'ramadan_hour_from_female': self.hour_from_female if self.mode == 'gender' else 0.0,
            'ramadan_hour_to_female': self.hour_to_female if self.mode == 'gender' else 0.0,
            'ramadan_notify_user_ids': [(6, 0, self.notify_user_ids.ids)],
            'ramadan_start_date': self.ramadan_date_start,
        })

        # 3. Email d'activation aux destinataires sélectionnés
        cal._notify_ramadan_activated()

        return {'type': 'ir.actions.act_window_close'}
