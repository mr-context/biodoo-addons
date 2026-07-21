{
    'name': 'Demandes RH',
    'version': '19.0.1.0.0',
    'summary': 'Demandes RH dynamiques depuis le portail (ordre de mission, bon de sortie, congé…)',
    'description': """
Demandes RH — Portail
======================
Extension du module Assistance pour gérer des demandes RH structurées :
- Types de demandes configurables (hr.request.type)
- Ordre de mission, Bon de sortie, Demande de congé pré-configurés
- Formulaire portail dynamique (dates, justification selon le type)
- Workflow Kanban hérité du module Assistance
- Création automatique de congé (hr.leave) à l'approbation si activé
    """,
    'category': 'Human Resources',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['assistance', 'hr', 'hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'data/hr_request_data.xml',
        'views/hr_request_type_views.xml',
        'views/assistance_ticket_views.xml',
        'views/hr_request_report.xml',
        'views/portal_templates.xml',
    ],
    'assets': {},
    'application': False,
    'installable': True,
    'auto_install': False,
}
