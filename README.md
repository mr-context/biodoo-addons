# biodoo-addons

![License: LGPL-3.0](https://img.shields.io/badge/License-LGPL_v3-blue.svg)

Modules Odoo **biodoo** — RH, paie, contrôle d'accès ZKTeco, localisation Algérie (l10n_dz).
Sous licence **LGPL-3**. Chaque module suit son propre versioning (champ `version` du manifeste).

## Installation

```bash
# ajouter ce dossier à l'addons_path d'Odoo, puis installer les modules voulus
```

## Modules (23)

| Module | Version | Description |
|---|---|---|
| `assistance` | 19.0.1.0.0 | Module de helpdesk générique — Communauté |
| `core_nats` | 19.0.2.0.0 | NATS JetStream infrastructure — pub/sub framework for connector module |
| `document_verification` | 19.0.1.0.0 | QR code on all reports linking to the source record for authenticity v |
| `hr_dz_attendance_anomaly` | 19.0.1.0.0 | Détection d |
| `hr_dz_base` | 19.0.1.0.0 | Module RH de base pour entreprises algériennes |
| `hr_dz_contract` | 19.0.1.0.0 | Gestion des contrats de travail algériens |
| `hr_dz_leave` | 19.0.1.0.0 | Droits au congé légal algérien calculés depuis le pointage (loi 90-11  |
| `hr_dz_loan` | 19.0.1.0.0 | Prêts salariaux sans intérêts avec remboursement flexible via bulletin |
| `hr_dz_ocr` | 19.0.2.0.0 | OCR local pour documents administratifs algériens |
| `hr_dz_payroll` | 19.0.1.0.0 | Extension de la paie pour l\ |
| `hr_dz_prime` | 19.0.1.0.0 | Gestion des primes exceptionnelles (Aïd, fin d |
| `hr_dz_requests` | 19.0.1.0.0 | Demandes RH dynamiques depuis le portail (ordre de mission, bon de sor |
| `hr_dz_sanction` | 19.0.1.0.0 | Procédures disciplinaires conformes à la Loi 90-11 Art.73, avec portai |
| `hr_dz_work_entry` | 19.0.1.0.0 | Génération automatique des prestations depuis les présences |
| `hr_employee_portal` | 19.0.1.0.0 | Portail RH employé — gestion des accès et documents |
| `hr_face_attendance` | 19.0.1.0.0 | Pointage facial depuis le portail employé (InsightFace + MiniFASNet) |
| `hr_ramadan_schedule` | 19.0.1.0.0 | Temporary schedule override for Ramadan period (uniform or gender-spli |
| `hr_shift_crossday` | 19.0.1.0.0 | Support for work schedules crossing midnight (night shifts) |
| `l10n_dz_base` | 19.0.1.0.0 | Wilayas et Communes d\ |
| `l10n_dz_company` | 19.0.1.0.0 | Identifiants légaux algériens sur la fiche société (NIF, NIS, RC, CNAS |
| `payroll` | 19.0.1.0.0 | Manage your employee payroll records |
| `web_enterprise` | 1.0 | Web Enterprise |
| `zkteco_connector` | 19.0.3.0.0 | ZKTeco ADMS via NATS — device approval, enrollment, check-in/out |

---
_Le bridge ZKTeco et le serveur de licences sont des composants séparés (non inclus)._
