"""
Barème IRG par lookup table — données exactes du tableau officiel DGI.

Usage : importer le fichier TABLE_IRG_2022_extracted.csv via le wizard.
Le calcul IRG utilisera ce tableau en priorité sur la formule mathématique.
"""

from odoo import models, fields, api


class HrIrgBareme(models.Model):
    """Conteneur d'un import du tableau DGI (ex: TABLE_IRG_2022)."""
    _name = 'hr.irg.bareme'
    _description = 'Barème IRG (lookup table DGI)'
    _order = 'date_import desc, id desc'

    name = fields.Char(string='Nom', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda self: self.env.company,
        required=True,
    )
    date_import = fields.Date(string='Date import', default=fields.Date.today)
    line_count = fields.Integer(
        string='Nb lignes', compute='_compute_line_count', store=True,
    )
    soumis_min = fields.Float(
        string='Soumis min (DA)', compute='_compute_bounds', store=True,
    )
    soumis_max = fields.Float(
        string='Soumis max (DA)', compute='_compute_bounds', store=True,
    )
    line_ids = fields.One2many(
        'hr.irg.bareme.line', 'bareme_id', string='Lignes',
    )
    irg_exemption_threshold = fields.Float(
        string='Seuil d\'exonération IRG (DA)',
        default=30000.0,
        help="Revenu mensuel imposable (après CNAS 9%) en dessous duquel l'IRG est nul. "
             "Mettre à jour si le seuil légal change (actuellement 30 000 DA). "
             "Référence : Art. 104 CIDTA / Loi de finances.",
    )
    notes = fields.Text(string='Notes')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('line_ids.soumis')
    def _compute_bounds(self):
        for rec in self:
            if rec.line_ids:
                soumis_vals = rec.line_ids.mapped('soumis')
                rec.soumis_min = min(soumis_vals)
                rec.soumis_max = max(soumis_vals)
            else:
                rec.soumis_min = 0.0
                rec.soumis_max = 0.0

    def get_irg(self, imposable, chef_famille=False):
        """Retourne l'IRG exact depuis le tableau DGI pour un imposable donné.

        Args:
            imposable (float): Revenu mensuel imposable (après CNAS 9%)
            chef_famille (bool): True = cas particuliers, False = cas général

        Returns:
            float or None: IRG dû, ou None si valeur hors table
        """
        self.ensure_one()

        # Exonération en dessous du seuil configurable (défaut 30 000 DA)
        threshold = self.irg_exemption_threshold or 30000.0
        if imposable <= threshold:
            return 0.0

        # Arrondir au multiple de 10 DA INFÉRIEUR (convention DGI, en faveur du salarié)
        soumis = int(imposable // 10) * 10

        # Chercher dans la table (par SQL direct pour performance)
        col = 'irg_particulier' if chef_famille else 'irg_general'
        self.env.cr.execute(
            f"SELECT {col} FROM hr_irg_bareme_line "
            f"WHERE bareme_id = %s AND soumis = %s LIMIT 1",
            (self.id, soumis),
        )
        row = self.env.cr.fetchone()
        if row is not None:
            return max(row[0], 0.0)

        # Valeur hors table (imposable > soumis_max) → None = utiliser fallback
        return None


class HrIrgBaremeLine(models.Model):
    """Une ligne du tableau DGI : (soumis → irg_general, irg_particulier)."""
    _name = 'hr.irg.bareme.line'
    _description = 'Ligne Barème IRG'

    bareme_id = fields.Many2one(
        'hr.irg.bareme', string='Barème',
        required=True, ondelete='cascade', index=True,
    )
    soumis = fields.Float(string='Mensuel soumis (DA)', required=True)
    irg_general = fields.Float(
        string='IRG cas général (DA)',
        help="IRG mensuel pour célibataire ou marié dont le conjoint travaille (tableau DGI).",
    )
    irg_particulier = fields.Float(
        string='IRG cas particuliers (DA)',
        help="IRG mensuel pour chef de famille : marié avec conjoint sans emploi, "
             "ou divorcé/veuf avec enfants à charge (Art. 71 CIDTA).",
    )

    _unique_soumis_per_bareme = models.Constraint(
        'UNIQUE(bareme_id, soumis)',
        'Un seul IRG par valeur de soumis dans le même barème.',
    )
