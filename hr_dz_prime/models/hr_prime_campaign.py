from odoo import api, fields, models
from odoo.exceptions import UserError


class HrPrimeCampaign(models.Model):
    _name = "hr.prime.campaign"
    _description = "Campagne de prime exceptionnelle"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="Libellé", required=True, tracking=True)
    type = fields.Selection(
        [
            ("aid", "Prime de l'Aïd"),
            ("fin_annee", "Prime de fin d'année"),
            ("exceptionnelle", "Prime exceptionnelle"),
            ("autre", "Autre"),
        ],
        string="Type",
        required=True,
        default="exceptionnelle",
        tracking=True,
    )
    date = fields.Date(string="Date de décision", required=True, default=fields.Date.today, tracking=True)
    mois_versement = fields.Selection(
        [
            ("1", "Janvier"), ("2", "Février"), ("3", "Mars"),
            ("4", "Avril"), ("5", "Mai"), ("6", "Juin"),
            ("7", "Juillet"), ("8", "Août"), ("9", "Septembre"),
            ("10", "Octobre"), ("11", "Novembre"), ("12", "Décembre"),
        ],
        string="Mois de versement",
        tracking=True,
        help="Mois du bulletin de paie sur lequel cette prime apparaîtra. "
             "Si non renseigné, le mois de la date de décision est utilisé.",
    )
    annee_versement = fields.Selection(
        [(str(y), str(y)) for y in range(2020, 2041)],
        string="Année de versement",
        tracking=True,
        help="Année du bulletin. Si non renseigné, l'année de la date de décision est utilisée.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Société",
        required=True,
        default=lambda self: self.env.company,
    )
    state = fields.Selection(
        [
            ("draft", "Brouillon"),
            ("confirmed", "Confirmée"),
            ("paid", "Payée"),
            ("cancelled", "Annulée"),
        ],
        string="État",
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many("hr.prime.line", "campaign_id", string="Lignes")
    line_count = fields.Integer(compute="_compute_line_count", string="Nb employés")
    total_amount = fields.Float(compute="_compute_totals", string="Montant total", store=True)
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Devise",
    )
    # ── Fiscalité ─────────────────────────────────────────────────────────
    is_cotisable = fields.Boolean(
        string="Cotisable (CNAS)",
        default=True,
        tracking=True,
        help="Incluse dans l'assiette de cotisation CNAS (Brut Cotisable).",
    )
    is_imposable = fields.Boolean(
        string="Imposable (IRG)",
        default=True,
        tracking=True,
        help="Incluse dans l'assiette imposable IRG.",
    )
    irg_mode = fields.Selection(
        [
            ("bareme", "Barème progressif (standard)"),
            ("forfaitaire", "Taux forfaitaire (libératoire)"),
        ],
        string="Mode IRG",
        default="bareme",
        tracking=True,
        help="Barème = IRG progressif standard. "
             "Forfaitaire = taux libératoire fixe (ex: 10%, 15%).",
    )
    irg_taux_forfait = fields.Float(
        string="Taux IRG forfaitaire (%)",
        digits=(5, 2),
        default=10.0,
        help="Taux libératoire appliqué si mode forfaitaire (ex: 10.0 = 10%).",
    )
    note = fields.Text(string="Notes")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends("line_ids.amount")
    def _compute_totals(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped("amount"))

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError("Impossible de confirmer une campagne sans lignes.")
            rec.state = "confirmed"

    def action_pay(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError("La campagne doit être confirmée avant le paiement.")
            rec.state = "paid"

    def action_cancel(self):
        for rec in self:
            if rec.state == "paid":
                raise UserError("Impossible d'annuler une campagne déjà payée.")
            rec.state = "cancelled"

    def action_draft(self):
        for rec in self:
            rec.state = "draft"

    # ── Helper pour les règles salariales ────────────────────────────────
    @api.model
    def get_employee_primes(self, employee_id, date_from, date_to):
        """Retourne les primes exceptionnelles pour un employé sur une période.

        Utilisé par les règles salariales pour intégrer les primes
        exceptionnelles dans le bulletin de paie.

        Returns:
            dict avec clés:
                cotisable: float — montant total des primes cotisables
                non_cotisable: float — montant total des primes non cotisables
                nc_imposable_bareme: float — non-cot + imposable + barème
                forfaitaire: list of (amount, taux) — primes avec IRG forfaitaire
        """
        # Cherche les campagnes dont le mois/année de versement
        # correspond à la période du bulletin
        campaigns = self.search([
            ("state", "in", ["confirmed", "paid"]),
        ])
        # Mois/année du bulletin (basé sur date_from)
        bull_month = date_from.month
        bull_year = date_from.year

        def _match(c):
            m = int(c.mois_versement) if c.mois_versement else c.date.month
            y = int(c.annee_versement) if c.annee_versement else c.date.year
            return m == bull_month and y == bull_year

        matching_campaigns = campaigns.filtered(_match)
        lines = self.env["hr.prime.line"].search([
            ("employee_id", "=", employee_id),
            ("campaign_id", "in", matching_campaigns.ids),
        ])
        result = {
            "cotisable": 0.0,
            "non_cotisable": 0.0,
            "nc_imposable_bareme": 0.0,
            "forfaitaire": [],
        }
        for line in lines:
            camp = line.campaign_id
            if camp.is_cotisable:
                result["cotisable"] += line.amount
            else:
                result["non_cotisable"] += line.amount
                if camp.is_imposable and camp.irg_mode == "bareme":
                    result["nc_imposable_bareme"] += line.amount
            # Forfaitaire : toute prime (cot ou non) avec IRG libératoire
            if camp.is_imposable and camp.irg_mode == "forfaitaire":
                result["forfaitaire"].append(
                    (line.amount, camp.irg_taux_forfait)
                )
        return result


class HrPrimeLine(models.Model):
    _name = "hr.prime.line"
    _description = "Ligne de prime exceptionnelle"
    _order = "employee_id"

    campaign_id = fields.Many2one(
        "hr.prime.campaign",
        string="Campagne",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employé",
        required=True,
    )
    matricule = fields.Char(related="employee_id.matricule", string="Matricule", store=True)
    department_id = fields.Many2one(
        related="employee_id.department_id",
        string="Département",
        store=True,
    )
    amount = fields.Float(string="Montant", required=True)
    state = fields.Selection(related="campaign_id.state", string="État", store=True)
    company_id = fields.Many2one(related="campaign_id.company_id", store=True)

    _sql_constraints = [
        (
            "unique_employee_campaign",
            "UNIQUE(campaign_id, employee_id)",
            "Un employé ne peut apparaître qu'une seule fois par campagne.",
        ),
    ]
