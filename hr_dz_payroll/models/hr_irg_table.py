
from odoo import models, fields, api


class HrIrgTable(models.Model):
    _name = 'hr.irg.table'
    _description = 'Table IRG'
    _order = 'id desc'

    name = fields.Char(string='Nom', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda self: self.env.company,
        required=True,
    )
    line_ids = fields.One2many(
        'hr.irg.table.line', 'table_id', string='Tranches',
        copy=True,
    )
    abatement_rate = fields.Float(
        string='Taux abattement', default=0.40,
        help='Taux d\'abattement sur l\'IRG brut (ex: 0.40 = 40%)',
    )
    abatement_min = fields.Float(
        string='Abattement min (DA/mois)', default=1000,
    )
    abatement_max = fields.Float(
        string='Abattement max (DA/mois)', default=1500,
    )
    exemption_threshold = fields.Float(
        string='Seuil exonération (DA/mois)', default=30000,
        help='Si imposable ≤ ce seuil, IRG = 0',
    )

    # --- Paramètres de décote (lissage au seuil d'exonération) ---
    # La décote évite le saut brutal d'IRG juste au-dessus du seuil d'exonération.
    # Formule : irg_net = irg_standard + k × (irg_standard - seuil)
    #           quand irg_standard < seuil  (sinon décote = 0)
    # Valeurs dérivées du tableau officiel DGI TABLE_IRG_2022.pdf
    decote_general_seuil = fields.Float(
        string='Seuil décote général (DA IRG)',
        default=2070.0,
        help='Valeur IRG standard (après abattement) au-delà de laquelle la décote '
             'cas général devient nulle. Correspond à imposable ≈ 35 000 DA. (LFC 2022)',
    )
    decote_general_k = fields.Float(
        string='Coeff. k décote général',
        default=1.686340,
        digits=(10, 6),
        help='Coefficient de la formule décote cas général. k = 1294.60 / 767.70',
    )
    decote_particulier_seuil = fields.Float(
        string='Seuil décote particulier (DA IRG)',
        default=3775.0,
        help='Valeur IRG standard (après abattement) au-delà de laquelle la décote '
             'cas particuliers devient nulle. Correspond à imposable ≈ 42 500 DA. (LFC 2022)',
    )
    decote_particulier_k = fields.Float(
        string='Coeff. k décote particulier',
        default=0.524764,
        digits=(10, 6),
        help='Coefficient de la formule décote cas particuliers. k = 1297.60 / 2472.70',
    )

    def compute_irg(self, imposable, chef_famille=False):
        """Calcul progressif IRG par tranche + abattement + décote.

        Args:
            imposable (float): Revenu mensuel imposable (après déduction CNAS 9%)
            chef_famille (bool): True = cas particuliers (chef de famille :
                marié dont le conjoint ne travaille pas, ou divorcé/veuf avec
                enfants à charge). False = cas général.

        Returns:
            float: IRG mensuel dû (positif)
        """
        self.ensure_one()

        # Exonération en dessous du seuil
        if imposable <= self.exemption_threshold:
            return 0.0

        # --- Calcul IRG brut par tranches progressives ---
        irg = 0.0
        for line in self.line_ids.sorted('sequence'):
            if imposable <= line.min_amount:
                break
            tranche_max = line.max_amount or float('inf')
            taxable_in_tranche = min(imposable, tranche_max) - line.min_amount
            if taxable_in_tranche > 0:
                irg += taxable_in_tranche * (line.rate / 100.0)

        # --- Abattement forfaitaire (Art. 104 CIDTA) ---
        if irg > 0 and self.abatement_rate:
            abattement = irg * self.abatement_rate
            abattement = min(max(abattement, self.abatement_min), self.abatement_max)
            irg -= abattement

        irg = max(irg, 0.0)

        # --- Décote (lissage au seuil d'exonération) ---
        # Évite le saut brutal de 0 à ~1300 DA juste au-dessus de 30 000 DA.
        # Source : tableau officiel DGI TABLE_IRG_2022.pdf
        if chef_famille:
            seuil = self.decote_particulier_seuil
            k = self.decote_particulier_k
        else:
            seuil = self.decote_general_seuil
            k = self.decote_general_k

        if seuil > 0 and k > 0 and irg < seuil:
            irg = irg + k * (irg - seuil)  # équivalent à irg*(1+k) - seuil*k
            irg = max(irg, 0.0)

        return irg


class HrIrgTableLine(models.Model):
    _name = 'hr.irg.table.line'
    _description = 'Tranche IRG'
    _order = 'sequence, id'

    table_id = fields.Many2one(
        'hr.irg.table', string='Table IRG',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Séq.', default=10)
    min_amount = fields.Float(string='Montant min (DA)', required=True)
    max_amount = fields.Float(
        string='Montant max (DA)',
        help='Laisser 0 pour la dernière tranche (illimité)',
    )
    rate = fields.Float(string='Taux (%)', required=True)


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def compute_irg(self, imposable, chef_famille=False):
        """Calcul IRG avec priorité : lookup table DGI > formule > fallback hardcodé.

        Priorité :
          1. Barème DGI actif (hr.irg.bareme) → valeurs exactes du tableau officiel
          2. Table formule active (hr.irg.table) → calcul paramétrable
          3. Fallback hardcodé → barème 2022 intégré dans le code

        Args:
            imposable (float): Revenu mensuel imposable (après CNAS 9%)
            chef_famille (bool): True = cas particuliers (chef de famille)
        """
        self.ensure_one()

        # 1. Lookup table DGI (valeurs exactes)
        bareme = self.env['hr.irg.bareme'].search([
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if bareme:
            result = bareme.get_irg(imposable, chef_famille=chef_famille)
            if result is not None:
                return result
            # result=None → imposable hors table (> soumis_max) → continuer

        # 2. Table formule paramétrée
        table = self.env['hr.irg.table'].search([
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if table:
            return table.compute_irg(imposable, chef_famille=chef_famille)

        # 3. Fallback hardcodé
        return self._compute_irg_fallback(imposable, chef_famille=chef_famille)

    def _compute_irg_fallback(self, imposable, chef_famille=False):
        """Barème IRG 2022 hardcodé (fallback si pas de table active).

        Tranches mensuelles (Art. 104 CIDTA amendé LFC 2022) :
          - 0 à 20 000 DA      : 0%
          - 20 001 à 40 000 DA : 23%
          - 40 001 à 80 000 DA : 27%
          - 80 001 à 160 000 DA: 30%
          - 160 001 à 320 000 DA: 33%
          - Au-delà de 320 000 DA: 35%
        Abattement : 40% (min 1 000, max 1 500 DA/mois)
        Seuil d'exonération : 30 000 DA/mois
        Décote : lissage au seuil (source tableau DGI 2022)
        """
        # Exonération en dessous du seuil
        if imposable <= 30000:
            return 0.0

        # --- Barème progressif ---
        if imposable <= 40000:
            irg = (imposable - 20000) * 0.23
        elif imposable <= 80000:
            irg = 20000 * 0.23 + (imposable - 40000) * 0.27
        elif imposable <= 160000:
            irg = 20000 * 0.23 + 40000 * 0.27 + (imposable - 80000) * 0.30
        elif imposable <= 320000:
            irg = 20000 * 0.23 + 40000 * 0.27 + 80000 * 0.30 + (imposable - 160000) * 0.33
        else:
            irg = 20000 * 0.23 + 40000 * 0.27 + 80000 * 0.30 + 160000 * 0.33 + (imposable - 320000) * 0.35

        # --- Abattement 40% (min 1 000, max 1 500 DA) ---
        abattement = min(max(irg * 0.40, 1000.0), 1500.0)
        irg -= abattement
        irg = max(irg, 0.0)

        # --- Décote (lissage au seuil d'exonération 30 000 DA) ---
        if chef_famille:
            seuil, k = 3775.0, 0.524764
        else:
            seuil, k = 2070.0, 1.686340

        if irg < seuil:
            irg = irg + k * (irg - seuil)
            irg = max(irg, 0.0)

        return irg
