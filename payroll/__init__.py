# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models
from . import report
from . import wizard


def _post_init_hook(env):
    """Add admin users to payroll manager group after installation."""
    payroll_manager_group = env.ref('payroll.group_payroll_manager', raise_if_not_found=False)
    if payroll_manager_group:
        # Add admin user to the group (Odoo 19: group_ids instead of groups_id)
        admin_user = env.ref('base.user_admin', raise_if_not_found=False)
        if admin_user:
            admin_user.write({'group_ids': [(4, payroll_manager_group.id)]})
        # Add root user to the group
        root_user = env.ref('base.user_root', raise_if_not_found=False)
        if root_user:
            root_user.write({'group_ids': [(4, payroll_manager_group.id)]})
