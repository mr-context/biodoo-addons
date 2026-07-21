{
    'name': 'Paie Algérienne - Extension',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Extension de la paie pour l\'Algérie',
    'description': """
        Extension du module Payroll pour les spécificités algériennes:
        - Structure salariale algérienne (CNAS, IRG)
        - Règles pour heures supplémentaires (50%, 75%, 100%) — Art. 32 Loi 90-11
        - Intégration avec les prestations (hr.work.entry)
    """,
    'author': 'MESSAOUDI ABDERRAOUF',
    'depends': [
        'payroll',
        'hr_attendance',
        'hr_dz_base',
        'hr_dz_contract',
        'hr_dz_work_entry',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_irg_table_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/ir_sequence_data.xml',
        'views/hr_payslip_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_irg_table_views.xml',
        'views/hr_irg_bareme_views.xml',
        'views/hr_dz_ats_views.xml',
        # doit charger APRÈS hr_dz_ats_views.xml qui définit menu_payroll_reports
        'views/hr_payslip_line_pivot_views.xml',
        'views/hr_dz_301bis_views.xml',
        'views/hr_dz_das_views.xml',
        'wizard/import_irg_bareme_views.xml',
        'wizard/hr_dz_releve_wizard_views.xml',
        'wizard/hr_dz_recap_paie_wizard_views.xml',
        'reports/reports.xml',
        'reports/report_ats.xml',
        'reports/report_301bis.xml',
        'reports/report_releve.xml',
        'reports/report_recap_paie.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
