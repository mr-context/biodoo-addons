{
    'name': 'HR Algérie — Sanctions disciplinaires',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Procédures disciplinaires conformes à la Loi 90-11 Art.73, avec portail employé',
    'description': """
Sanctions disciplinaires — Loi 90-11 Art.73
============================================
- 4 degrés de sanctions configurables
- Workflow : Incident → Convocation → Audition → Décision → Notification
- L'employé suit sa procédure en temps réel depuis le portail
- L'employé soumet sa réponse d'audition depuis le portail
- PDFs : convocation + décision téléchargeables
- Chatter + activités Odoo natif
    """,
    'author': 'MESSAOUDI ABDERRAOUF',
    'license': 'LGPL-3',
    'depends': ['hr', 'mail', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_sanction_data.xml',
        'views/hr_sanction_config_views.xml',
        'views/hr_sanction_views.xml',
        'views/hr_employee_views.xml',
        'report/report_menu.xml',
        'report/report_convocation.xml',
        'report/report_decision.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
