
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrDzAts(models.Model):
    _name = 'hr.dz.ats'
    _description = 'Attestation de Travail et de Salaire (ATS)'
    _order = 'id desc'

    name = fields.Char(string='Référence', readonly=True, copy=False, default='/')
    employee_id = fields.Many2one('hr.employee', string='Employé', required=True)
    company_id = fields.Many2one(
        'res.company', string='Société', default=lambda self: self.env.company,
    )
    date_from = fields.Date(string='Date début', required=True, index=True)
    date_to = fields.Date(string='Date fin', required=True, index=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('done', 'Confirmé'),
    ], string='État', default='draft', readonly=True, copy=False)
    line_ids = fields.One2many('hr.dz.ats.line', 'ats_id', string='Lignes mensuelles')

    # Related employee fields
    matricule = fields.Char(related='employee_id.matricule', string='Matricule')
    birthday = fields.Date(related='employee_id.birthday', string='Date de naissance')
    place_of_birth = fields.Char(related='employee_id.place_of_birth', string='Lieu de naissance')
    job_id = fields.Many2one(related='employee_id.job_id', string='Fonction')
    identification_id = fields.Char(
        related='employee_id.identification_id', string='N° Sécurité Sociale',
    )

    # Computed totals
    total_base_cotisable = fields.Float(
        string='Total base cotisable', compute='_compute_totals', store=True,
    )
    total_retenue_ss = fields.Float(
        string='Total retenue SS', compute='_compute_totals', store=True,
    )

    @api.depends('line_ids.base_cotisable', 'line_ids.retenue_ss')
    def _compute_totals(self):
        for rec in self:
            rec.total_base_cotisable = sum(rec.line_ids.mapped('base_cotisable'))
            rec.total_retenue_ss = sum(rec.line_ids.mapped('retenue_ss'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.dz.ats') or '/'
        return super().create(vals_list)

    def action_load(self):
        """Load payslip data for the employee over the period, one line per month."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Vous ne pouvez charger que les ATS en brouillon.'))

            payslips = self.env['hr.payslip'].search([
                ('employee_id', '=', rec.employee_id.id),
                ('state', '=', 'done'),
                ('date_from', '>=', rec.date_from),
                ('date_to', '<=', rec.date_to),
            ], order='date_from')

            if not payslips:
                raise UserError(_(
                    'Aucun bulletin confirmé trouvé pour %(employee)s '
                    'sur la période %(from)s - %(to)s.'
                ) % {
                    'employee': rec.employee_id.name,
                    'from': rec.date_from,
                    'to': rec.date_to,
                })

            # Supprimer les lignes existantes (remplacement complet)
            if rec.line_ids:
                _logger.info(
                    'ATS %s : remplacement de %d ligne(s) pour %s (%s → %s)',
                    rec.name, len(rec.line_ids), rec.employee_id.name,
                    rec.date_from, rec.date_to,
                )
                rec.line_ids.unlink()

            lines_vals = []
            for slip in payslips:
                period = slip.date_from.strftime('%m/%Y')
                gross = self._get_line_amount(slip, 'GROSS')
                cnas_sal = abs(self._get_line_amount(slip, 'CNAS_SAL'))
                nb_jours = sum(
                    slip.worked_days_line_ids.filtered(
                        lambda w: w.code in ('WORK100', 'FERIE')
                    ).mapped('number_of_days')
                )
                lines_vals.append({
                    'ats_id': rec.id,
                    'period': period,
                    'period_date': slip.date_from.replace(day=1),
                    'nb_jours': nb_jours,
                    'base_cotisable': gross,
                    'retenue_ss': cnas_sal,
                })

            self.env['hr.dz.ats.line'].create(lines_vals)

    def _get_line_amount(self, slip, code):
        """Extract total amount for a salary rule code from a payslip."""
        line = slip.line_ids.filtered(lambda l: l.code == code)
        return line[:1].total if line else 0.0

    def action_confirm(self):
        self.write({'state': 'done'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        return self.env.ref('hr_dz_payroll.action_report_ats').report_action(self)


class HrDzAtsLine(models.Model):
    _name = 'hr.dz.ats.line'
    _description = 'Ligne ATS (mois)'
    _order = 'period_date'

    ats_id = fields.Many2one('hr.dz.ats', string='ATS', ondelete='cascade', required=True)
    period = fields.Char(string='Période')
    period_date = fields.Date(string='Date période')
    nb_jours = fields.Float(string='Jours de présence')
    base_cotisable = fields.Float(string='Base cotisable')
    retenue_ss = fields.Float(string='Retenue SS')
