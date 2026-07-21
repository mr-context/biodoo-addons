from odoo import fields, models


class ResourceCalendarAttendance(models.Model):
    _inherit = 'resource.calendar.attendance'

    original_hour_from = fields.Float(
        string='Orig. Début',
        digits=(4, 2),
        help="Heure de début originale sauvegardée avant activation du mode Ramadan.",
    )
    original_hour_to = fields.Float(
        string='Orig. Fin',
        digits=(4, 2),
        help="Heure de fin originale sauvegardée avant activation du mode Ramadan.",
    )
