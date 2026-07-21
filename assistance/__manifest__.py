{
    'name': 'Assistance',
    'version': '19.0.1.0.0',
    'summary': 'Module de helpdesk générique — Communauté',
    'description': """
Assistance — Helpdesk générique
================================
Module de ticketing utilisable par n'importe quel service
(RH, IT, Finance…) sans dépendance à la version Enterprise.

Fonctionnalités :
- Tickets avec références automatiques (AT0001…)
- Équipes et étapes configurables
- Vue Kanban groupée par étape
- Portail employé : création et suivi des demandes
- Chatter complet (mail.thread)
    """,
    'category': 'Services/Assistance',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['portal', 'mail'],
    'data': [
        'security/assistance_security.xml',
        'security/ir.model.access.csv',
        'data/assistance_data.xml',
        'views/assistance_stage_views.xml',
        'views/assistance_team_views.xml',
        'views/assistance_ticket_views.xml',
        'views/assistance_menus.xml',
        'views/portal_templates.xml',
    ],
    'assets': {},
    'application': True,
    'installable': True,
    'auto_install': False,
    'icon': '/assistance/static/src/img/portal-assistance.svg',
}
