{
    'name': 'HR Algérie - Prêts salariaux',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Prêts salariaux sans intérêts avec remboursement flexible via bulletin de paie',
    'author': 'MESSAOUDI ABDERRAOUF',
    'license': 'LGPL-3',
    'depends': [
        'hr_dz_requests',
        'hr_dz_payroll',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_loan_data.xml',
        'views/hr_loan_views.xml',
        'views/hr_loan_report.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
