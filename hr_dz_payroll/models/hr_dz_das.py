"""
Déclaration Annuelle des Salaires (DAS) — CNAS / Tasrihatcom 2025.

Génère les deux fichiers à largeur fixe requis par la plateforme CNAS :
  D{AAAA}E{num_employeur}.txt  — Fichier Entête Employeur  (216 chars)
  D{AAAA}S{num_employeur}.txt  — Fichier Détail Salariés   (229 chars/ligne)

Encodage : Windows-1252 (ANSI) — requis par le portail Tasrihatcom.
Structure conforme au format Tasrihatcom 2025 (avec Durée+Unité par trimestre).
"""

import base64
import calendar
from collections import defaultdict
from datetime import date as date_cls

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# ---------------------------------------------------------------------------
# Helpers de formatage (Guide CNAS §4)
# ---------------------------------------------------------------------------

def _fmt_alpha(val, length):
    """Texte : majuscules, cadré à gauche, complété par espaces."""
    return str(val or '').upper().ljust(length)[:length]


def _fmt_num(val, length):
    """Numérique : cadré à droite par zéros."""
    return str(int(val or 0)).zfill(length)[:length]


def _fmt_amount(val, length):
    """Montant en centimes (×100), sans virgule, cadré à droite par zéros."""
    centimes = int(round(float(val or 0.0) * 100))
    return str(centimes).zfill(length)[:length]


def _fmt_date(val):
    """Date → JJMMAAAA (8 cars). Retourne 8 espaces si absent."""
    if isinstance(val, date_cls):
        return val.strftime('%d%m%Y')
    return ' ' * 8


def _trimestre(month):
    """Retourne le numéro de trimestre (1-4) pour un mois donné."""
    return (month - 1) // 3 + 1


def _split_nom_prenom(employee):
    """Retourne (nom_famille, prenom) depuis les champs dédiés de l'employé.
    Fallback sur détection par casse si les champs ne sont pas renseignés.
    """
    nom    = (employee.nom_famille or '').strip()
    prenom = (employee.prenom or '').strip()
    if nom or prenom:
        return nom, prenom
    # Fallback : détection par convention MAJUSCULES / mixte
    words = (employee.name or '').strip().split()
    nom_parts, prenom_parts = [], []
    in_prenom = False
    for word in words:
        if not in_prenom and word.isalpha() and word == word.upper():
            nom_parts.append(word)
        else:
            in_prenom = True
            prenom_parts.append(word)
    return ' '.join(nom_parts), ' '.join(prenom_parts)


# ---------------------------------------------------------------------------
# Modèle principal
# ---------------------------------------------------------------------------

class HrDzDas(models.Model):
    """Déclaration Annuelle des Salaires (DAS) CNAS — Tasrihatcom."""

    _name = 'hr.dz.das'
    _description = 'Déclaration Annuelle des Salaires (DAS) CNAS'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Référence', readonly=True, copy=False, default='/',
    )

    @api.model
    def _year_selection(self):
        current = date_cls.today().year
        return [(str(y), str(y)) for y in range(current - 6, current + 1)]

    year = fields.Selection(
        selection='_year_selection',
        string='Année civile', required=True,
        default=lambda self: str(date_cls.today().year - 1),
        help='Année fiscale déclarée',
    )
    company_id = fields.Many2one(
        'res.company', string='Société',
        default=lambda self: self.env.company,
        required=True,
    )
    type_declaration = fields.Selection([
        ('N', 'Normale'),
        ('C', 'Complémentaire'),
    ], string='Type de déclaration', default='N', required=True)

    num_employeur_cnas = fields.Char(
        related='company_id.num_employeur_cnas',
        string='N° Employeur CNAS',
        readonly=False, store=True,
        help='Récupéré depuis les paramètres société — modifiable ici pour cette déclaration.',
    )
    centre_payeur = fields.Char(
        related='company_id.centre_payeur_cnas',
        string='Centre Payeur',
        readonly=False, store=True,
        help='Récupéré depuis les paramètres société.',
    )
    denomination = fields.Char(
        related='company_id.name',
        string='Dénomination sociale',
        readonly=False, store=True,
        help='Récupéré depuis le nom de la société — modifiable ici.',
    )

    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('done', 'Confirmé'),
    ], string='État', default='draft', readonly=True, copy=False)

    line_ids = fields.One2many(
        'hr.dz.das.line', 'das_id', string='Lignes salariés',
    )

    # Fichiers générés (stockés en base64)
    file_employer = fields.Binary(
        string='Fichier Entête Employeur', readonly=True, copy=False,
        attachment=False,
    )
    file_employer_name = fields.Char(
        string='Nom fichier entête', readonly=True, copy=False,
    )
    file_salarie = fields.Binary(
        string='Fichier Détail Salariés', readonly=True, copy=False,
        attachment=False,
    )
    file_salarie_name = fields.Char(
        string='Nom fichier salariés', readonly=True, copy=False,
    )

    # Totaux calculés
    total_t1 = fields.Float(
        string='Total T1', compute='_compute_totals', store=True, digits=(16, 2),
    )
    total_t2 = fields.Float(
        string='Total T2', compute='_compute_totals', store=True, digits=(16, 2),
    )
    total_t3 = fields.Float(
        string='Total T3', compute='_compute_totals', store=True, digits=(16, 2),
    )
    total_t4 = fields.Float(
        string='Total T4', compute='_compute_totals', store=True, digits=(16, 2),
    )
    total_assiette = fields.Float(
        string='Total annuel', compute='_compute_totals', store=True,
    )
    nbr_salaries = fields.Integer(
        string='Nombre de salariés', compute='_compute_totals', store=True,
    )

    @api.depends('line_ids.assiette_t1', 'line_ids.assiette_t2',
                 'line_ids.assiette_t3', 'line_ids.assiette_t4')
    def _compute_totals(self):
        for rec in self:
            rec.total_t1 = sum(rec.line_ids.mapped('assiette_t1'))
            rec.total_t2 = sum(rec.line_ids.mapped('assiette_t2'))
            rec.total_t3 = sum(rec.line_ids.mapped('assiette_t3'))
            rec.total_t4 = sum(rec.line_ids.mapped('assiette_t4'))
            rec.total_assiette = rec.total_t1 + rec.total_t2 + rec.total_t3 + rec.total_t4
            rec.nbr_salaries = len(rec.line_ids)

    @api.onchange('year')
    def _onchange_year(self):
        """Recharge les lignes automatiquement quand l'année change."""
        if self.year and self._origin.id and self.state == 'draft':
            try:
                self.action_load()
            except UserError:
                self.line_ids = [(5, 0, 0)]  # vide si aucun bulletin

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.dz.das') or '/'
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: r.year and r.state == 'draft'):
            try:
                rec.action_load()
            except UserError:
                pass
        return records

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_load(self):
        """Charge les lignes depuis les bulletins confirmés de l'année."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Vous ne pouvez charger que les DAS en brouillon.'))

        year = int(self.year)
        year_start = date_cls(year, 1, 1)
        year_end   = date_cls(year, 12, 31)

        self.line_ids.unlink()

        all_payslips = self.env['hr.payslip'].search([
            ('state', '=', 'done'),
            ('date_from', '>=', year_start),
            ('date_to', '<=', year_end),
            ('company_id', '=', self.company_id.id),
        ])

        if not all_payslips:
            raise UserError(
                _('Aucun bulletin confirmé trouvé pour l\'année %s.') % self.year
            )

        all_payslips.mapped('line_ids')

        # data[emp_id] = {trim: {'assiette': float, 'mois': set()}}
        data      = defaultdict(lambda: {1: {'assiette': 0.0, 'mois': set()},
                                          2: {'assiette': 0.0, 'mois': set()},
                                          3: {'assiette': 0.0, 'mois': set()},
                                          4: {'assiette': 0.0, 'mois': set()}})
        dates_by_emp = {}

        for slip in all_payslips:
            emp_id    = slip.employee_id.id
            assiette  = self._get_gross(slip)
            trimestre = _trimestre(slip.date_from.month)
            data[emp_id][trimestre]['assiette'] += assiette
            data[emp_id][trimestre]['mois'].add(slip.date_from.month)

            if emp_id not in dates_by_emp:
                dates_by_emp[emp_id] = {'first': slip.date_from, 'last': slip.date_to}
            else:
                if slip.date_from < dates_by_emp[emp_id]['first']:
                    dates_by_emp[emp_id]['first'] = slip.date_from
                if slip.date_to > dates_by_emp[emp_id]['last']:
                    dates_by_emp[emp_id]['last'] = slip.date_to

        if not data:
            raise UserError(
                _('Aucun code GROSS trouvé dans les bulletins pour l\'année %s.') % self.year
            )

        lines_to_create = []
        for emp_id, trimestres in data.items():
            first_date = dates_by_emp[emp_id]['first']
            last_date  = dates_by_emp[emp_id]['last']
            last_month = last_date.month
            last_day   = calendar.monthrange(year, last_month)[1]
            date_sortie = date_cls(year, last_month, last_day) if last_month < 12 else False

            emp = self.env['hr.employee'].browse(emp_id)
            observation = (emp.job_id.name or '')[:50] if emp.job_id else ''

            lines_to_create.append({
                'das_id':       self.id,
                'employee_id':  emp_id,
                'assiette_t1':  trimestres[1]['assiette'],
                'assiette_t2':  trimestres[2]['assiette'],
                'assiette_t3':  trimestres[3]['assiette'],
                'assiette_t4':  trimestres[4]['assiette'],
                'duree_t1':     len(trimestres[1]['mois']),
                'duree_t2':     len(trimestres[2]['mois']),
                'duree_t3':     len(trimestres[3]['mois']),
                'duree_t4':     len(trimestres[4]['mois']),
                'unite_mesure': 'M',
                'date_entree':  first_date,
                'date_sortie':  date_sortie,
                'observation':  observation,
            })

        self.env['hr.dz.das.line'].create(lines_to_create)

    def _get_gross(self, slip):
        """Retourne le montant GROSS (brut cotisable) d'un bulletin."""
        line = slip.line_ids.filtered(lambda l: l.code == 'GROSS')
        return line[:1].total if line else 0.0

    def action_generate_files(self):
        """Génère les deux fichiers Tasrihatcom et les stocke sur le record."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Chargez d\'abord les données (bouton "Charger").'))

        num_emp = (self.num_employeur_cnas or '').strip()
        if not num_emp:
            raise UserError(
                _('Renseignez le N° Employeur CNAS dans Paramètres > Société > Identifiants CNAS.')
            )

        # Vérifier que tous les employés ont un NSS valide et une date de naissance
        import re
        invalid = []
        for line in self.line_ids:
            emp = line.employee_id
            nss = re.sub(r'[\s\-]', '', emp.ssnid or '')
            if not re.match(r'^\d{12}$', nss):
                invalid.append(_('• %s : NSS manquant ou invalide') % emp.name)
            if not emp.birthday:
                invalid.append(_('• %s : date de naissance manquante') % emp.name)
        if invalid:
            raise UserError(
                _('Impossible de générer les fichiers — données manquantes :\n\n%s')
                % '\n'.join(invalid)
            )
        employer_content = self._generate_file_employer(num_emp)
        salarie_content  = self._generate_file_salarie(num_emp)

        # Noms fichiers : D{AAAA}E{num}.TXT et D{AAAA}S{num}.TXT
        fname_employer = 'D%sE%s.TXT' % (self.year, num_emp)
        fname_salarie  = 'D%sS%s.TXT' % (self.year, num_emp)

        self.write({
            'file_employer':      base64.b64encode(
                employer_content.encode('windows-1252', errors='replace')
            ),
            'file_employer_name': fname_employer,
            'file_salarie':       base64.b64encode(
                salarie_content.encode('windows-1252', errors='replace')
            ),
            'file_salarie_name':  fname_salarie,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Fichiers générés'),
                'message': _('Fichiers créés : %s et %s') % (fname_employer, fname_salarie),
                'type':    'success',
                'sticky': False,
            },
        }

    def _generate_file_employer(self, num_emp):
        """
        Fichier Entête Employeur — 216 caractères (format CNAS officiel).

        N° Employeur       10  num
        Type déclaration    1  alpha  (N/C)
        Année Réf           4  num
        Centre Payeur       5  num
        Dénomination       30  alpha
        Nom/Raison Sociale 30  alpha
        Adresse            50  alphanum
        Montant T1         16  centimes
        Montant T2         16  centimes
        Montant T3         16  centimes
        Montant T4         16  centimes
        Total Annuel       16  centimes
        Nb Travailleurs     6  num
        Total             216
        """
        company = self.company_id
        address_parts = [company.street or '', company.city or '', company.zip or '']
        address = ', '.join(p for p in address_parts if p)

        line = (
            _fmt_num(num_emp, 10)
            + _fmt_alpha(self.type_declaration, 1)
            + _fmt_num(self.year, 4)
            + _fmt_num(self.centre_payeur or '', 5)
            + _fmt_alpha(self.denomination or company.name, 30)
            + _fmt_alpha(company.name, 30)
            + _fmt_alpha(address, 50)
            + _fmt_amount(self.total_t1, 16)
            + _fmt_amount(self.total_t2, 16)
            + _fmt_amount(self.total_t3, 16)
            + _fmt_amount(self.total_t4, 16)
            + _fmt_amount(self.total_assiette, 16)
            + _fmt_num(self.nbr_salaries, 6)
        )
        assert len(line) == 216, f"Entête employeur : {len(line)} chars (attendu 216)"
        return line + '\r\n'

    def _generate_file_salarie(self, num_emp):
        """
        Fichier Détail Salariés — 229 caractères par ligne (format Tasrihatcom 2025).

        N° Employeur        10  num
        Année Réf            4  num
        N° Ligne             5  num
        N° Immat + Clé      12  num  (NSS)
        Nom                 30  alpha
        Prénom              30  alpha
        Date Naissance       8  jjmmaaaa
        Durée T1             3  num   (nb mois)
        Unité T1             1  alpha (M/J/H)
        Assiette T1         12  centimes
        Durée T2             3  num
        Unité T2             1  alpha
        Assiette T2         12  centimes
        Durée T3             3  num
        Unité T3             1  alpha
        Assiette T3         12  centimes
        Durée T4             3  num
        Unité T4             1  alpha
        Assiette T4         12  centimes
        Date Entrée          8  jjmmaaaa
        Date Sortie          8  jjmmaaaa ou 00000000 si encore en poste
        Observation         50  alphanum  (titre/poste)
        Total              229
        """
        lines = []
        for idx, line in enumerate(
            self.line_ids.sorted(lambda l: (l.employee_id.name or '')), start=1
        ):
            emp  = line.employee_id
            nom, prenom = _split_nom_prenom(emp)
            nss = (emp.ssnid or '').replace(' ', '')
            unite = line.unite_mesure or 'M'
            date_sortie = _fmt_date(line.date_sortie) if line.date_sortie else '00000000'

            row = (
                _fmt_num(num_emp, 10)
                + _fmt_num(self.year, 4)
                + _fmt_num(idx, 5)
                + _fmt_num(nss, 12)
                + _fmt_alpha(nom, 30)
                + _fmt_alpha(prenom, 30)
                + _fmt_date(emp.birthday)
                + _fmt_num(line.duree_t1, 3)
                + _fmt_alpha(unite, 1)
                + _fmt_amount(line.assiette_t1, 12)
                + _fmt_num(line.duree_t2, 3)
                + _fmt_alpha(unite, 1)
                + _fmt_amount(line.assiette_t2, 12)
                + _fmt_num(line.duree_t3, 3)
                + _fmt_alpha(unite, 1)
                + _fmt_amount(line.assiette_t3, 12)
                + _fmt_num(line.duree_t4, 3)
                + _fmt_alpha(unite, 1)
                + _fmt_amount(line.assiette_t4, 12)
                + _fmt_date(line.date_entree)
                + date_sortie
                + _fmt_alpha(line.observation or '', 50)
            )
            assert len(row) == 229, f"Ligne salarié {emp.name} : {len(row)} chars (attendu 229)"
            lines.append(row)

        return '\r\n'.join(lines) + ('\r\n' if lines else '')

    def action_confirm(self):
        self.write({'state': 'done'})

    def action_draft(self):
        self.write({'state': 'draft'})


# ---------------------------------------------------------------------------
# Ligne par salarié
# ---------------------------------------------------------------------------

class HrDzDasLine(models.Model):
    """Ligne DAS : assiettes et durées trimestrielles d'un salarié."""

    _name = 'hr.dz.das.line'
    _description = 'Ligne DAS Salarié'
    _order = 'employee_id'

    das_id = fields.Many2one(
        'hr.dz.das', string='DAS', ondelete='cascade', required=True, index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employé', required=True,
    )
    ssnid = fields.Char(
        related='employee_id.ssnid', string='N° Sécurité Sociale',
    )
    matricule = fields.Char(
        related='employee_id.matricule', string='Matricule',
    )

    # Assiettes trimestrielles (brut cotisable)
    assiette_t1 = fields.Float(string='Assiette T1 (Jan-Mar)', digits=(16, 2))
    assiette_t2 = fields.Float(string='Assiette T2 (Avr-Jun)', digits=(16, 2))
    assiette_t3 = fields.Float(string='Assiette T3 (Jul-Sep)', digits=(16, 2))
    assiette_t4 = fields.Float(string='Assiette T4 (Oct-Déc)', digits=(16, 2))

    # Durées de travail par trimestre (nombre de mois cotisés)
    duree_t1 = fields.Integer(string='Durée T1 (mois)', default=0)
    duree_t2 = fields.Integer(string='Durée T2 (mois)', default=0)
    duree_t3 = fields.Integer(string='Durée T3 (mois)', default=0)
    duree_t4 = fields.Integer(string='Durée T4 (mois)', default=0)

    unite_mesure = fields.Selection([
        ('M', 'Mensuel (M)'),
        ('J', 'Journalier (J)'),
        ('H', 'Horaire (H)'),
    ], string='Unité de mesure', default='M', required=True)

    total_annuel = fields.Float(
        string='Total annuel', compute='_compute_total', store=True, digits=(16, 2),
    )

    date_entree = fields.Date(string='Date d\'entrée')
    date_sortie = fields.Date(
        string='Date de sortie',
        help='Laisser vide si le salarié est encore en poste au 31/12',
    )
    observation = fields.Char(
        string='Observation (poste/fonction)',
        size=50,
        help='Titre ou poste du salarié — 50 caractères max (Tasrihatcom 2025)',
    )

    @api.depends('assiette_t1', 'assiette_t2', 'assiette_t3', 'assiette_t4')
    def _compute_total(self):
        for rec in self:
            rec.total_annuel = (
                rec.assiette_t1 + rec.assiette_t2
                + rec.assiette_t3 + rec.assiette_t4
            )
