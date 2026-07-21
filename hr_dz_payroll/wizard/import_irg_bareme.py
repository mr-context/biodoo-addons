"""
Wizard d'import du tableau IRG DGI (format CSV extrait du PDF officiel).

Format CSV attendu (TABLE_IRG_2022_extracted.csv) :
    soumis,irg_general,net_general,irg_particulier,net_particulier
    20000.00,0.00,20000.00,0.00,20000.00
    ...

Seules les colonnes soumis, irg_general et irg_particulier sont utilisées.
"""

import base64
import csv
import io
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BATCH_SIZE = 2000  # lignes insérées par batch


class ImportIrgBaremeWizard(models.TransientModel):
    _name = 'import.irg.bareme.wizard'
    _description = 'Import Barème IRG depuis CSV DGI'

    name = fields.Char(
        string='Nom du barème',
        default='Barème IRG 2022',
        required=True,
    )
    csv_file = fields.Binary(string='Fichier CSV', required=True)
    csv_filename = fields.Char(string='Nom fichier')
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda self: self.env.company,
        required=True,
    )
    notes = fields.Text(
        string='Notes',
        default='Source : TABLE_IRG_2022.pdf (DGI Algérie)',
    )
    line_count = fields.Integer(
        string='Lignes détectées', readonly=True,
        help='Calculé après sélection du fichier.',
    )

    def action_import(self):
        """Parse le CSV et crée le barème avec toutes ses lignes."""
        self.ensure_one()

        if not self.csv_file:
            raise UserError(_("Veuillez sélectionner un fichier CSV."))

        # Décodage du fichier
        try:
            content = base64.b64decode(self.csv_file).decode('utf-8')
        except Exception as e:
            raise UserError(_("Impossible de lire le fichier : %s") % str(e))

        # Parsing CSV
        reader = csv.DictReader(io.StringIO(content))

        required_cols = {'soumis', 'irg_general', 'irg_particulier'}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            raise UserError(_(
                "Le fichier CSV doit contenir les colonnes : %s\n"
                "Colonnes détectées : %s"
            ) % (', '.join(required_cols), ', '.join(reader.fieldnames or [])))

        rows = []
        for i, row in enumerate(reader, start=2):
            try:
                soumis = float(row['soumis'])
                irg_g = float(row['irg_general'])
                irg_p = float(row['irg_particulier'])
                rows.append((soumis, irg_g, irg_p))
            except (ValueError, KeyError) as e:
                raise UserError(
                    _("Erreur ligne %d : %s") % (i, str(e))
                )

        if not rows:
            raise UserError(_("Le fichier CSV ne contient aucune donnée."))

        # Créer le barème
        bareme = self.env['hr.irg.bareme'].create({
            'name': self.name,
            'company_id': self.company_id.id,
            'date_import': fields.Date.today(),
            'notes': self.notes,
        })

        # Insertion en batch via SQL (31 001 lignes → beaucoup plus rapide que l'ORM)
        cr = self.env.cr
        total = 0
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start:start + BATCH_SIZE]
            values = [(bareme.id, s, g, p) for s, g, p in batch]
            cr.executemany(
                """
                INSERT INTO hr_irg_bareme_line
                    (bareme_id, soumis, irg_general, irg_particulier)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (bareme_id, soumis) DO UPDATE
                    SET irg_general = EXCLUDED.irg_general,
                        irg_particulier = EXCLUDED.irg_particulier
                """,
                values,
            )
            total += len(batch)
            _logger.info("Import IRG : %d/%d lignes insérées", total, len(rows))

        # Invalider le cache Odoo pour le nouveau bareme
        bareme.invalidate_recordset()

        _logger.info(
            "Import barème IRG '%s' terminé : %d lignes (soumis %.0f → %.0f DA)",
            bareme.name, len(rows),
            rows[0][0] if rows else 0,
            rows[-1][0] if rows else 0,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Barème IRG importé'),
            'res_model': 'hr.irg.bareme',
            'res_id': bareme.id,
            'view_mode': 'form',
            'target': 'current',
        }
