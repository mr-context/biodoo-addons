from odoo import models, fields, api


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # =========================================================================
    # CHAMPS CONFIGURATION
    # =========================================================================

    # ── Mutuelle (Art. 70 CIDTA) ──────────────────────────────────────────────
    mutuelle_taux = fields.Float(
        string='Taux mutuelle (%)',
        digits=(5, 2),
        default=0.0,
        help="Taux de cotisation mutuelle en % du brut cotisable. "
             "0 = pas de mutuelle. Déductible du net imposable (Art. 70 CIDTA).",
    )

    # ── CNAS Patronale ────────────────────────────────────────────────────────
    cnas_patron_taux_special = fields.Float(
        string='Taux CNAS patronal spécial (%)',
        digits=(5, 2),
        help="Taux de cotisation patronale CNAS dérogatoire (ex: ANEM, ANSEJ). "
             "Laissez à 0 pour appliquer le taux standard de 26%.",
    )
    cnas_patron_date_debut = fields.Date(
        string='Début taux spécial',
        help="Date de début d'application du taux spécial.",
    )
    cnas_patron_date_fin = fields.Date(
        string='Fin taux spécial',
        help="Date de fin d'application du taux spécial. "
             "Après cette date, le taux standard de 26% s'applique.",
    )

    # =========================================================================
    # MÉTHODES MÉTIER — SOURCE UNIQUE DE VÉRITÉ
    # Appelées à la fois par les règles de paie (XML) ET par la simulation.
    # Modifier ici = modifier partout.
    # =========================================================================

    def is_chef_famille(self):
        """Statut chef de famille pour abattement IRG (Art. 71 CIDTA).

        Retourne True si :
          - Marié dont le conjoint ne travaille pas
          - OU divorcé/veuf avec enfants à charge
        """
        self.ensure_one()
        emp = self.employee_id
        if not emp:
            return False
        marital = emp.marital or 'single'
        if marital == 'married' and not (emp.conjoint_travaille or False):
            return True
        if marital in ('widower', 'divorced') and (emp.nb_enfants_charge or 0) > 0:
            return True
        return False

    def compute_mutuelle(self, gross):
        """Cotisation mutuelle (Art. 70 CIDTA) — déductible du net imposable.

        Args:
            gross: Salaire brut cotisable (assiette CNAS)
        Returns:
            Montant de la retenue mutuelle (positif)
        """
        self.ensure_one()
        return round(gross * (self.mutuelle_taux or 0.0) / 100.0, 2)

    def compute_psu(self):
        """Prime de Salaire Unique (Décret 25-168).

        Versée au salarié marié dont le conjoint n'exerce pas d'activité.
        NON cotisable / NON imposable — remboursée par la CNAS.
        Montant configurable via hr.legal.parameter code='psu_montant' (défaut 800 DA).
        """
        self.ensure_one()
        emp = self.employee_id
        if (emp
                and (emp.marital or 'single') == 'married'
                and not (emp.conjoint_travaille or False)):
            montant = self.env['hr.legal.parameter'].get_value('psu_montant')
            return montant or 800.0
        return 0.0

    def compute_af(self, gross):
        """Allocations Familiales (Décret 25-168).

        Taux et seuil configurables via hr.legal.parameter :
          af_rate_low (défaut 600), af_rate_high (défaut 300), af_threshold (défaut 15000)
        NON cotisable / NON imposable — remboursée par la CNAS.
        """
        self.ensure_one()
        enfants = (self.employee_id.nb_enfants_charge or 0) if self.employee_id else 0
        if not enfants:
            return 0.0
        param = self.env['hr.legal.parameter']
        seuil = param.get_value('af_threshold') or 15000.0
        rate_low = param.get_value('af_rate_low') or 600.0
        rate_high = param.get_value('af_rate_high') or 300.0
        taux = rate_low if gross <= seuil else rate_high
        return taux * enfants

    def compute_scolarite(self):
        """Prime de Scolarité (Décret 25-168).

        Montant configurable via hr.legal.parameter code='scolarite_montant' (défaut 3000).
        Versée en septembre uniquement (condition mois=9 gérée dans la règle de paie).
        """
        self.ensure_one()
        enfants_sco = (
            self.employee_id.nb_enfants_scolarises or 0
        ) if self.employee_id else 0
        montant = self.env['hr.legal.parameter'].get_value('scolarite_montant') or 3000.0
        return montant * enfants_sco

    def get_cnas_patron_rate(self, date):
        """Taux CNAS patronal applicable à la date donnée.

        Retourne le taux spécial si la date est dans la période configurée,
        sinon le taux standard 26% (25% CNAS + 0,5% FNPOS + 0,5% OS).
        """
        self.ensure_one()
        if (self.cnas_patron_taux_special
                and self.cnas_patron_date_debut
                and self.cnas_patron_date_fin
                and self.cnas_patron_date_debut <= date <= self.cnas_patron_date_fin):
            return self.cnas_patron_taux_special
        return self.env['hr.legal.parameter'].get_value('cnas_employer_rate') or 26.0

    # =========================================================================
    # SIMULATION SALAIRE THÉORIQUE (mois complet, aucune absence)
    # Utilise UNIQUEMENT les méthodes métier ci-dessus — aucune logique dupliquée.
    # Si une règle change, la simulation change automatiquement.
    # =========================================================================
    sim_is_september = fields.Boolean(
        string='Simuler septembre',
        default=False,
        help="Cochez pour simuler un mois de septembre : inclut la prime de scolarité "
             "(3 000 DA × enfants scolarisés) dans le Net à Payer.",
    )

    sim_basic = fields.Float(
        string='Salaire de base', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_transport = fields.Float(
        string='Indemnité Transport (non cotisable)', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_panier = fields.Float(
        string='Indemnité Panier (non cotisable)', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_non_cot = fields.Float(
        string='Total indemnités non cotisables', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_primes = fields.Float(
        string='Primes', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_brut = fields.Float(
        string='Salaire Brut Cotisable', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_brut_total = fields.Float(
        string='Total Brut Versé', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_psu = fields.Float(
        string='PSU (Prime de Salaire Unique)', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_af = fields.Float(
        string='Allocations Familiales', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_scolarite = fields.Float(
        string='Prime de Scolarité (septembre)', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_cnas = fields.Float(
        string='CNAS Salarié (9%)', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_mutuelle = fields.Float(
        string='Mutuelle', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_imposable = fields.Float(
        string='Net Imposable', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_irg = fields.Float(
        string='IRG', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_net = fields.Float(
        string='Net à Payer', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_cnas_patr = fields.Float(
        string='CNAS Patronale', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )
    sim_cout_employeur = fields.Float(
        string='Coût Total Employeur', compute='_compute_simulation',
        digits=(16, 2), store=False,
    )

    # =========================================================================
    # CALCUL INVERSE — Du NET vers Salaire de Base
    # =========================================================================
    sim_target_net = fields.Float(
        string='NET souhaité (DA)',
        digits=(16, 2),
        help="Saisissez le net à payer souhaité pour calculer le salaire de base nécessaire.",
    )
    sim_reverse_wage = fields.Float(
        string='Salaire de base nécessaire (hors primes)',
        compute='_compute_reverse_salary',
        digits=(16, 2), store=False,
        help="Salaire de base pour atteindre le NET cible, calculé sans les primes "
             "contractuelles. Les primes s'ajoutent en supplément.",
    )
    sim_reverse_imposable = fields.Float(
        string='Net imposable (hors primes)',
        compute='_compute_reverse_salary',
        digits=(16, 2), store=False,
    )
    sim_reverse_irg = fields.Float(
        string='IRG (hors primes)',
        compute='_compute_reverse_salary',
        digits=(16, 2), store=False,
    )
    sim_reverse_brut = fields.Float(
        string='Brut cotisable (hors primes)',
        compute='_compute_reverse_salary',
        digits=(16, 2), store=False,
    )
    sim_reverse_net_with_primes = fields.Float(
        string='NET estimé (avec primes)',
        compute='_compute_reverse_salary',
        digits=(16, 2), store=False,
        help="NET à payer estimé si ce salaire de base est appliqué avec les primes "
             "contractuelles actuelles du contrat.",
    )

    @api.depends(
        'sim_target_net',
        'working_days_per_month',
        'transport_allowance_enabled', 'daily_transport_allowance',
        'meal_allowance_enabled', 'daily_meal_allowance',
        'prime_line_ids.amount',
        'prime_line_ids.is_cotisable',
        'prime_line_ids.is_imposable',
        'employee_id.marital',
        'employee_id.conjoint_travaille',
        'employee_id.nb_enfants_charge',
        'employee_id.is_handicap',
        'mutuelle_taux',
        'company_id',
    )
    def _compute_reverse_salary(self):
        """Calcul inverse : trouve le salaire de base pour un NET cible donné.

        La dichotomie ignore les primes contractuelles (ignore_primes=True) afin
        que le résultat soit le salaire de base pur, indépendant des primes.
        Un second calcul (avec primes) estime le NET réel final.
        """
        for version in self:
            target = version.sim_target_net or 0.0
            if target <= 0:
                version.sim_reverse_wage = 0.0
                version.sim_reverse_imposable = 0.0
                version.sim_reverse_irg = 0.0
                version.sim_reverse_brut = 0.0
                version.sim_reverse_net_with_primes = 0.0
                continue

            lo, hi = 0.0, target * 3  # borne sup large
            # 50 itérations → précision < 0.01 DA
            for _i in range(50):
                mid = (lo + hi) / 2.0
                net = version._net_for_wage(mid)  # ignore_primes=True par défaut
                if net < target:
                    lo = mid
                else:
                    hi = mid

            wage = round((lo + hi) / 2.0, 2)
            # Résultats sans primes (base pure)
            result = version._simulation_detail_for_wage(wage, ignore_primes=True)
            version.sim_reverse_wage = wage
            version.sim_reverse_imposable = result['imposable']
            version.sim_reverse_irg = result['irg']
            version.sim_reverse_brut = result['brut_cot']
            # NET estimé quand les primes contractuelles s'ajoutent sur ce wage
            result_with = version._simulation_detail_for_wage(wage, ignore_primes=False)
            version.sim_reverse_net_with_primes = result_with['net']

    def _net_for_wage(self, wage):
        """Calcule le NET pour un salaire de base donné (hors primes, mois complet)."""
        return self._simulation_detail_for_wage(wage, ignore_primes=True)['net']

    def _simulation_detail_for_wage(self, wage, ignore_primes=False):
        """Reproduit la logique _compute_simulation pour un wage donné.

        Args:
            wage: Salaire de base à simuler.
            ignore_primes: Si True, les primes contractuelles sont exclues du calcul
                           (utile pour le calcul inverse — salaire de base pur).

        Retourne un dict avec brut_cot, cnas, imposable, irg, net.
        """
        self.ensure_one()
        param = self.env['hr.legal.parameter']
        cap_enabled = bool(param.get_value('transport_meal_cap_enabled'))
        transport_cap = param.get_value('transport_daily_cap') or 250.0
        meal_cap = param.get_value('meal_daily_cap') or 250.0
        cnas_rate = (param.get_value('cnas_worker_rate') or 9.0) / 100.0

        jours = self.working_days_per_month or 22

        transport_non_cot = transport_cot = 0.0
        if self.transport_allowance_enabled:
            t = self.daily_transport_allowance or 0.0
            if cap_enabled:
                transport_non_cot = min(t, transport_cap) * jours
                transport_cot = max(0.0, t - transport_cap) * jours
            else:
                transport_non_cot = t * jours

        panier_non_cot = panier_cot = 0.0
        if self.meal_allowance_enabled:
            p = self.daily_meal_allowance or 0.0
            if cap_enabled:
                panier_non_cot = min(p, meal_cap) * jours
                panier_cot = max(0.0, p - meal_cap) * jours
            else:
                panier_non_cot = p * jours

        if ignore_primes:
            primes_cot = primes_nc_imp = primes_nc = 0.0
        else:
            primes_cot = sum(l.amount or 0.0 for l in self.prime_line_ids if l.is_cotisable)
            primes_nc_imp = sum(
                l.amount or 0.0 for l in self.prime_line_ids
                if not l.is_cotisable and l.is_imposable
            )
            primes_nc = sum(l.amount or 0.0 for l in self.prime_line_ids if not l.is_cotisable)

        non_cot = transport_non_cot + panier_non_cot + primes_nc

        brut_cot = wage + transport_cot + panier_cot + primes_cot
        cnas = round(brut_cot * cnas_rate, 2)
        mutuelle = self.compute_mutuelle(brut_cot)
        imposable = round(brut_cot - cnas - mutuelle + transport_non_cot + panier_non_cot + primes_nc_imp, 2)

        irg = 0.0
        is_handicap = self.employee_id.is_handicap if self.employee_id else False
        if not is_handicap and imposable > 0:
            try:
                irg = self.compute_irg(imposable, chef_famille=self.is_chef_famille())
            except Exception:
                irg = 0.0

        psu = self.compute_psu()
        net = round(brut_cot - cnas - mutuelle - irg + non_cot + psu, 2)

        return {
            'brut_cot': brut_cot,
            'cnas': cnas,
            'imposable': imposable,
            'irg': irg,
            'net': net,
        }

    def action_apply_reverse_wage(self):
        """Bouton : applique le salaire de base calculé par le calcul inverse."""
        self.ensure_one()
        if self.sim_reverse_wage > 0:
            self.wage = self.sim_reverse_wage

    @api.depends(
        'sim_is_september',
        'wage', 'working_days_per_month',
        'transport_allowance_enabled', 'daily_transport_allowance',
        'meal_allowance_enabled', 'daily_meal_allowance',
        'prime_line_ids.amount',
        'prime_line_ids.is_cotisable',
        'prime_line_ids.is_imposable',
        'employee_id.marital',
        'employee_id.conjoint_travaille',
        'employee_id.nb_enfants_charge',
        'employee_id.nb_enfants_scolarises',
        'employee_id.is_handicap',
        'cnas_patron_taux_special',
        'cnas_patron_date_debut',
        'cnas_patron_date_fin',
        'mutuelle_taux',
        'company_id',
    )
    def _compute_simulation(self):
        from datetime import date as date_cls
        today = date_cls.today()

        param = self.env['hr.legal.parameter']
        cap_enabled = bool(param.get_value('transport_meal_cap_enabled'))
        transport_cap = param.get_value('transport_daily_cap') or 250.0
        meal_cap = param.get_value('meal_daily_cap') or 250.0
        cnas_sal_rate = (param.get_value('cnas_worker_rate') or 9.0) / 100.0

        for version in self:
            jours = version.working_days_per_month or 22
            wage = version.wage or 0.0

            # ── Transport : règle cap DA/j (Instruction CNAS n°02/2011) ──
            transport_non_cot = 0.0
            transport_cot = 0.0
            if version.transport_allowance_enabled:
                t_daily = version.daily_transport_allowance or 0.0
                if cap_enabled:
                    transport_non_cot = min(t_daily, transport_cap) * jours
                    transport_cot = max(0.0, t_daily - transport_cap) * jours
                else:
                    transport_non_cot = t_daily * jours

            # ── Panier : règle cap DA/j ───────────────────────────────────
            panier_non_cot = 0.0
            panier_cot = 0.0
            if version.meal_allowance_enabled:
                p_daily = version.daily_meal_allowance or 0.0
                if cap_enabled:
                    panier_non_cot = min(p_daily, meal_cap) * jours
                    panier_cot = max(0.0, p_daily - meal_cap) * jours
                else:
                    panier_non_cot = p_daily * jours

            primes_cot = sum(
                l.amount or 0.0 for l in version.prime_line_ids if l.is_cotisable
            )
            primes_nc = sum(
                l.amount or 0.0 for l in version.prime_line_ids if not l.is_cotisable
            )
            primes_nc_imp = sum(
                l.amount or 0.0 for l in version.prime_line_ids
                if not l.is_cotisable and l.is_imposable
            )
            primes = primes_cot + primes_nc
            non_cot = transport_non_cot + panier_non_cot + primes_nc

            # ── Brut Cotisable ─────────────────────────────────────────────
            brut_cot = wage + transport_cot + panier_cot + primes_cot

            # ── Retenues — via méthodes métier partagées ───────────────────
            cnas = round(brut_cot * cnas_sal_rate, 2)
            mutuelle = version.compute_mutuelle(brut_cot)
            # Transport/Panier ≤ 500 DA/j : exonérés CNAS mais imposables IRG (Art. 104 CIDTA)
            # Primes non-cotisables imposables : ajoutées à l'assiette IRG
            imposable = round(brut_cot - cnas - mutuelle + transport_non_cot + panier_non_cot + primes_nc_imp, 2)

            irg = 0.0
            emp = version.employee_id
            is_handicap = emp.is_handicap if emp else False
            if not is_handicap and imposable > 0:
                try:
                    irg = version.compute_irg(
                        imposable,
                        chef_famille=version.is_chef_famille(),
                    )
                except Exception:
                    irg = 0.0

            # ── Prestations Familiales — via méthodes métier partagées ─────
            psu = version.compute_psu()
            af = version.compute_af(brut_cot)
            scolarite = version.compute_scolarite()  # info (sept. uniquement)

            # ── CNAS Patronale ─────────────────────────────────────────────
            cnas_patr = round(
                brut_cot * version.get_cnas_patron_rate(today) / 100.0, 2
            )

            # ── Affectation ────────────────────────────────────────────────
            version.sim_basic = wage
            version.sim_transport = transport_non_cot
            version.sim_panier = panier_non_cot
            version.sim_non_cot = non_cot
            version.sim_primes = primes
            version.sim_brut = brut_cot
            version.sim_brut_total = round(brut_cot + non_cot, 2)
            version.sim_psu = psu
            version.sim_af = af
            version.sim_scolarite = scolarite
            version.sim_cnas = cnas
            version.sim_mutuelle = mutuelle
            version.sim_imposable = imposable
            version.sim_irg = irg
            # NET = Brut − CNAS − Mutuelle − IRG + NON_COT + PSU
            # AF exclues du NET (remboursées par la CNAS, convention PC Paie)
            # Scolarité incluse uniquement si toggle "Simuler septembre" actif
            scolarite_net = scolarite if version.sim_is_september else 0.0
            version.sim_net = round(
                brut_cot - cnas - mutuelle - irg + non_cot + psu + scolarite_net, 2
            )
            version.sim_cnas_patr = cnas_patr
            # Coût employeur : brut cotisable + CNAS patr
            # PSU/AF non comptés : remboursés par la CNAS à l'employeur
            version.sim_cout_employeur = round(brut_cot + cnas_patr, 2)
