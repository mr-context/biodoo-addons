{
    "name": "BioDoo Suite",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "summary": "Méta-module : installe l'ensemble de la suite BioDoo (RH, paie, pointage ZKTeco, portail) en un clic",
    "description": """
BioDoo Suite
============
Module « parapluie » sans code propre. Il déclare comme dépendances tous les
modules de la suite BioDoo : installer celui-ci installe (et met à jour) toute
la suite d'un seul coup.

Désinstaller ce module NE désinstalle PAS les autres — Odoo ne retire pas
automatiquement les dépendances.
""",
    "author": "MESSAOUDI ABDERRAOUF",
    "license": "LGPL-3",
    "application": True,
    "installable": True,
    "auto_install": False,
    # Toute la suite. Les dépendances transitives (l10n_dz_base, hr_dz_base,
    # core_nats, payroll…) sont listées explicitement pour documenter le
    # périmètre et survivre à un refactor de dépendances.
    "depends": [
        # Socle & localisation Algérie
        "l10n_dz_base",
        "l10n_dz_company",
        "hr_dz_base",
        # Paie & contrats
        "payroll",
        "hr_dz_contract",
        "hr_dz_payroll",
        "hr_dz_prime",
        "hr_dz_work_entry",
        # Congés, prêts, sanctions, demandes
        "hr_dz_leave",
        "hr_dz_loan",
        "hr_dz_sanction",
        "hr_dz_requests",
        # Présence & pointage
        "hr_dz_attendance_anomaly",
        "hr_ramadan_schedule",
        "hr_shift_crossday",
        "hr_face_attendance",
        # Connecteur ZKTeco (bridge NATS)
        "core_nats",
        "zkteco_connector",
        # OCR, portail employé, helpdesk, vérification documents
        # (hr_assistant retiré : module IA expérimental abandonné, non publié)
        "hr_dz_ocr",
        "hr_employee_portal",
        "assistance",
        "document_verification",
        # Backend
        "web_enterprise",
    ],
    "data": [],
}