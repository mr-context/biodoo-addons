{
    'name': 'HR Ramadan Schedule',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Temporary schedule override for Ramadan period (uniform or gender-split)',
    'description': """
        Adds a Ramadan mode toggle to work schedules (resource.calendar).
        When activated via wizard, temporarily overrides all attendance lines
        with Ramadan-specific hours. Supports uniform (all staff) or
        gender-split (men/women with different start and end times).
        Notifies HR managers by email to remember to deactivate at Ramadan's end.
    """,
    'author': 'MESSAOUDI ABDERRAOUF',
    'depends': ['hr', 'resource', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'wizards/hr_ramadan_wizard_views.xml',
        'views/resource_calendar_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
