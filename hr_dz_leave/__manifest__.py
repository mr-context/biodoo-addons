{
    'name': 'HR Algérie - Congés annuels',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Droits au congé légal algérien calculés depuis le pointage (loi 90-11 art. 26)',
    'description': """
HR Algérie - Congés annuels
============================

Calcul des droits au congé annuel basé sur le pointage réel (hr.attendance).

Formule : taux / jours_ouvrables_du_mois × jours_pointés

- Taux configurables sur le contrat : 2.5 j/mois (légal) ou 1.5 j/mois
- Cron journalier (6h) : traite les pointages de la veille
- Proportionnel : 11j pointés sur 22 → 1.25j de droit
- Précis au jour près (utile en cas de démission)
- Solde visible sur le portail employé (/my/attendances)
- Wizard de backfill initial depuis l'historique pointage
    """,
    'author': 'MESSAOUDI ABDERRAOUF',
    'website': 'https://msd.com',
    'license': 'LGPL-3',
    'depends': [
        'hr_holidays',
        'hr_employee_portal',
        'hr_dz_contract',
        'hr_dz_work_entry',
        'hr_dz_requests',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_dz_leave_data.xml',
        'data/ir_cron_data.xml',
        'views/hr_version_views.xml',
        'views/portal_templates.xml',
        'views/hr_leave_views.xml',
        'views/hr_leave_report.xml',
        'wizard/hr_dz_accrual_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
