# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Adapted for Odoo 19: hr.contract replaced by hr.version

from odoo import fields, models


class HrVersion(models.Model):
    """
    Extension of hr.version (employee contract/version in Odoo 19)
    to add payroll-specific fields for salary structure configuration.

    Note: In Odoo 19, hr.contract has been replaced by hr.version.
    This model extends hr.version with payroll functionality.
    """

    _inherit = "hr.version"

    struct_id = fields.Many2one(
        "hr.payroll.structure",
        string="Salary Structure",
        help="Defines the rules that have to be applied to this payslip.",
    )
    schedule_pay = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("semi-annually", "Semi-annually"),
            ("annually", "Annually"),
            ("weekly", "Weekly"),
            ("bi-weekly", "Bi-weekly"),
            ("bi-monthly", "Bi-monthly"),
        ],
        string="Scheduled Pay",
        index=True,
        default="monthly",
        help="Defines the frequency of the wage payment.",
    )

    def get_all_structures(self):
        """
        @return: the structures linked to the given contracts, ordered by
                 hierarchy (parent=False first, then first level children and
                 so on) and without duplicates
        """
        return self.struct_id.get_structure_with_parents()
