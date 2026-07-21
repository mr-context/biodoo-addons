{
    "name": "Primes Exceptionnelles",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Gestion des primes exceptionnelles (Aïd, fin d'année, etc.) avec import Excel",
    "author": "Messaoudi Abderrouf",
    "depends": ["hr_dz_base", "hr_dz_payroll", "assistance"],
    "data": [
        "security/ir.model.access.csv",
        "data/hr_prime_salary_rules.xml",
        "wizard/hr_prime_import_views.xml",
        "views/hr_prime_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
