from odoo import api, fields, models


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    is_crossday = fields.Boolean(
        string='Shift traversant minuit',
        default=False,
        help="Activer pour les équipes de nuit dont la plage horaire dépasse minuit "
             "(ex: 22:00 → 06:00). Saisir l'heure de fin réelle, le jour de sortie s'affiche automatiquement."
    )

    @api.onchange('is_crossday')
    def _onchange_is_crossday(self):
        """Quand on désactive le mode crossday, ramener les hour_to > 24 à leur valeur naturelle."""
        if not self.is_crossday:
            for line in self.attendance_ids:
                if line.hour_to >= 24.0:
                    line.hour_to = line.hour_to - 24.0


class ResourceCalendarAttendance(models.Model):
    _inherit = 'resource.calendar.attendance'

    crossday_hour_to = fields.Float(
        string='Heure fin',
        compute='_compute_crossday_hour_to',
        inverse='_inverse_crossday_hour_to',
    )
    crossday_day_to = fields.Char(
        string='Jour fin',
        compute='_compute_crossday_day_to',
    )

    @api.depends('hour_to')
    def _compute_crossday_hour_to(self):
        for rec in self:
            rec.crossday_hour_to = rec.hour_to - 24.0 if rec.hour_to >= 24.0 else rec.hour_to

    def _inverse_crossday_hour_to(self):
        for rec in self:
            val = rec.crossday_hour_to or 0.0
            if rec.calendar_id.is_crossday and val < (rec.hour_from or 0.0):
                rec.hour_to = val + 24.0
            else:
                rec.hour_to = val

    @api.depends('dayofweek', 'hour_to')
    def _compute_crossday_day_to(self):
        day_names = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
        for rec in self:
            if rec.hour_to and rec.hour_to >= 24.0 and rec.dayofweek is not False:
                next_idx = (int(rec.dayofweek) + 1) % 7
                rec.crossday_day_to = day_names[next_idx]
            else:
                rec.crossday_day_to = ''

    @api.onchange('hour_from', 'hour_to')
    def _onchange_hours(self):
        # Triggered when hour_to is edited directly (non-crossday mode, or edge cases)
        if self.calendar_id.is_crossday:
            self.hour_from = min(max(self.hour_from or 0.0, 0.0), 23.99)
            self.hour_to = max(self.hour_to or 0.0, 0.0)
            if self.hour_to and self.hour_to < self.hour_from:
                self.hour_to += 24.0
            self.hour_to = min(self.hour_to, 47.99)
        else:
            # Comportement Odoo standard (réplication fidèle de l'original)
            self.hour_from = min(self.hour_from or 0.0, 23.99)
            self.hour_from = max(self.hour_from, 0.0)
            self.hour_to = min(self.hour_to or 0.0, 24.0)
            self.hour_to = max(self.hour_to, 0.0)
            self.hour_to = max(self.hour_to, self.hour_from)
