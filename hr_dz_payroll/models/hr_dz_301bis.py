
import calendar
from collections import defaultdict
from datetime import date as date_cls

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrDz301bis(models.Model):
    _name = 'hr.dz.301bis'
    _description = 'État 301 Bis - Relevé des Émoluments'
    _order = 'id desc'

    name = fields.Char(string='Référence', readonly=True, copy=False, default='/')
    year = fields.Char(string='Année fiscale', required=True)
    company_id = fields.Many2one(
        'res.company', string='Société', default=lambda self: self.env.company,
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('done', 'Confirmé'),
    ], string='État', default='draft', readonly=True, copy=False)
    employee_ids = fields.One2many(
        'hr.dz.301bis.employee', 'bis_id', string='Employés',
    )

    # Computed totals
    total_imposable = fields.Float(
        string='Total base imposable', compute='_compute_totals', store=True,
    )
    total_irg = fields.Float(
        string='Total IRG', compute='_compute_totals', store=True,
    )
    nbr_employees = fields.Integer(
        string="Nombre d'employés", compute='_compute_totals', store=True,
    )

    @api.depends('employee_ids.total_imp', 'employee_ids.total_irg')
    def _compute_totals(self):
        for rec in self:
            rec.total_imposable = sum(rec.employee_ids.mapped('total_imp'))
            rec.total_irg = sum(rec.employee_ids.mapped('total_irg'))
            rec.nbr_employees = len(rec.employee_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.dz.301bis') or '/'
        return super().create(vals_list)

    def action_load(self):
        """Load all employees with confirmed payslips for the year."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Vous ne pouvez charger que les états en brouillon.'))

            year = int(rec.year)
            rec.employee_ids.unlink()

            year_start = date_cls(year, 1, 1)
            year_end = date_cls(year, 12, 31)

            # 1 seule requête pour tous les bulletins de l'année, filtrée par société
            all_payslips = self.env['hr.payslip'].search([
                ('state', '=', 'done'),
                ('date_from', '>=', year_start),
                ('date_to', '<=', year_end),
                ('company_id', '=', rec.company_id.id),
            ])

            if not all_payslips:
                raise UserError(_(
                    'Aucun bulletin confirmé trouvé pour l\'année %s.'
                ) % rec.year)

            # Précharger les lignes de bulletin en une seule requête
            all_payslips.mapped('line_ids')

            # Regrouper par employé et mois en Python (zéro requête supplémentaire)
            data = defaultdict(lambda: defaultdict(list))
            for slip in all_payslips:
                data[slip.employee_id.id][slip.date_from.month].append(slip)

            # Créer toutes les lignes en un seul appel create()
            lines_to_create = []
            for employee_id, months in data.items():
                vals = {'bis_id': rec.id, 'employee_id': employee_id}
                has_data = False
                for month, slips in months.items():
                    base_imp = sum(self._get_line_amount(slip, 'IMPOSABLE') for slip in slips)
                    irg = sum(abs(self._get_line_amount(slip, 'IRG')) for slip in slips)
                    if base_imp > 0 or irg > 0:
                        month_str = f'{month:02d}'
                        vals[f'base_{month_str}'] = base_imp
                        vals[f'irg_{month_str}'] = irg
                        has_data = True
                if has_data:
                    lines_to_create.append(vals)

            if lines_to_create:
                self.env['hr.dz.301bis.employee'].create(lines_to_create)
            else:
                raise UserError(_(
                    'Aucun bulletin confirmé trouvé pour l\'année %s.'
                ) % rec.year)

    def _get_line_amount(self, slip, code):
        """Extract total amount for a salary rule code from a payslip."""
        line = slip.line_ids.filtered(lambda l: l.code == code)
        return line[:1].total if line else 0.0

    def action_confirm(self):
        self.write({'state': 'done'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        return self.env.ref('hr_dz_payroll.action_report_301bis').report_action(self)


class HrDz301bisEmployee(models.Model):
    _name = 'hr.dz.301bis.employee'
    _description = 'Ligne employé 301 Bis'
    _order = 'employee_id'

    bis_id = fields.Many2one('hr.dz.301bis', string='301 Bis', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employé', required=True)
    matricule = fields.Char(related='employee_id.matricule', string='Matricule')
    identification_id = fields.Char(
        related='employee_id.identification_id', string='N° Sécurité Sociale',
    )
    birthday = fields.Date(related='employee_id.birthday', string='Date de naissance')

    # 12 monthly base imposable fields
    base_01 = fields.Float('Base Janvier')
    base_02 = fields.Float('Base Février')
    base_03 = fields.Float('Base Mars')
    base_04 = fields.Float('Base Avril')
    base_05 = fields.Float('Base Mai')
    base_06 = fields.Float('Base Juin')
    base_07 = fields.Float('Base Juillet')
    base_08 = fields.Float('Base Août')
    base_09 = fields.Float('Base Septembre')
    base_10 = fields.Float('Base Octobre')
    base_11 = fields.Float('Base Novembre')
    base_12 = fields.Float('Base Décembre')

    # 12 monthly IRG fields
    irg_01 = fields.Float('IRG Janvier')
    irg_02 = fields.Float('IRG Février')
    irg_03 = fields.Float('IRG Mars')
    irg_04 = fields.Float('IRG Avril')
    irg_05 = fields.Float('IRG Mai')
    irg_06 = fields.Float('IRG Juin')
    irg_07 = fields.Float('IRG Juillet')
    irg_08 = fields.Float('IRG Août')
    irg_09 = fields.Float('IRG Septembre')
    irg_10 = fields.Float('IRG Octobre')
    irg_11 = fields.Float('IRG Novembre')
    irg_12 = fields.Float('IRG Décembre')

    # Computed totals
    total_imp = fields.Float(
        string='Total imposable', compute='_compute_total_imp', store=True,
    )
    total_irg = fields.Float(
        string='Total IRG', compute='_compute_total_irg', store=True,
    )

    @api.depends('base_01', 'base_02', 'base_03', 'base_04', 'base_05', 'base_06',
                 'base_07', 'base_08', 'base_09', 'base_10', 'base_11', 'base_12')
    def _compute_total_imp(self):
        for rec in self:
            rec.total_imp = sum(
                getattr(rec, f'base_{m:02d}') for m in range(1, 13)
            )

    @api.depends('irg_01', 'irg_02', 'irg_03', 'irg_04', 'irg_05', 'irg_06',
                 'irg_07', 'irg_08', 'irg_09', 'irg_10', 'irg_11', 'irg_12')
    def _compute_total_irg(self):
        for rec in self:
            rec.total_irg = sum(
                getattr(rec, f'irg_{m:02d}') for m in range(1, 13)
            )
