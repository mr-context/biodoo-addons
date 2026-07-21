"""
Wizard OCR pour documents administratifs algériens.
Traitement asynchrone avec progression temps réel via bus.bus.
"""

import base64
import json
import logging
import threading

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']

# Conversion ISO 3166-1 alpha-3 → alpha-2 pour res.country
_ALPHA3_TO_ALPHA2 = {
    'DZA': 'DZ', 'FRA': 'FR', 'MAR': 'MA', 'TUN': 'TN',
    'LBY': 'LY', 'MRT': 'MR', 'EGY': 'EG', 'MLI': 'ML',
    'NIG': 'NE', 'BEL': 'BE', 'DEU': 'DE', 'ITA': 'IT',
    'ESP': 'ES', 'GBR': 'GB', 'USA': 'US', 'CAN': 'CA',
    'SAU': 'SA', 'ARE': 'AE', 'TUR': 'TR', 'CHN': 'CN',
    'SEN': 'SN', 'CMR': 'CM', 'CIV': 'CI', 'GHA': 'GH',
}


class HrOcrWizard(models.TransientModel):
    _name = 'hr.ocr.wizard'
    _description = 'OCR Document Wizard'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employé',
        required=True,
        default=lambda self: self.env.context.get('active_id'),
    )
    document_type = fields.Selection([
        ('auto', 'Détection automatique'),
        ('birth_certificate', 'Acte de Naissance'),
        ('passport', 'Passeport'),
        ('id_card', "Carte d'Identité Nationale"),
        ('driver_license', 'Permis de Conduire'),
        ('carte_chiffa', 'Carte Chiffa (CNAS)'),
    ], string='Type de Document', required=True, default='auto')

    document_file = fields.Binary(string='Document (PDF/Image)', required=True)
    document_filename = fields.Char(string='Nom du fichier')

    state = fields.Selection([
        ('upload', 'Upload'),
        ('processing', 'Traitement en cours...'),
        ('preview', 'Preview'),
        ('error', 'Erreur'),
    ], default='upload')

    # ── Champs extraits ────────────────────────────────────────────────
    extracted_name_fr = fields.Char(string='Nom (Français)')
    extracted_name_ar = fields.Char(string='الاسم بالعربية')
    extracted_birth_date = fields.Date(string='Date de naissance')
    extracted_birth_place = fields.Char(string='Lieu de naissance')
    extracted_act_number = fields.Char(string='N° Acte')
    extracted_father_name = fields.Char(string='Prénom du père')
    extracted_mother_name = fields.Char(string='Nom et prénom de la mère')
    extracted_gender = fields.Selection([
        ('male', 'Masculin'),
        ('female', 'Féminin'),
    ], string='Genre')
    extracted_document_number = fields.Char(string='N° Document')
    extracted_nationality = fields.Char(string='Nationalité (code)')
    extracted_expiry_date = fields.Date(string="Date d'expiration")
    extracted_mrz_text = fields.Text(string='MRZ brut')
    extracted_ssnid = fields.Char(string='N° SS (NSS) — 12 chiffres')

    # ── Métadonnées détection ──────────────────────────────────────────
    doc_side = fields.Selection([
        ('recto', 'Recto — MRZ présente'),
        ('verso', 'Verso — MRZ absente'),
    ], string='Face détectée', readonly=True)
    is_auto_detected = fields.Boolean(string='Détecté automatiquement', default=False)

    validation_errors = fields.Text(string='Erreurs', readonly=True)
    ocr_raw_text = fields.Text(string='Réponse brute', readonly=True)

    # ── Helpers ────────────────────────────────────────────────────────

    def _check_file_extension(self, filename):
        if not filename:
            return True
        ext = '.' + filename.lower().split('.')[-1]
        return ext in ALLOWED_EXTENSIONS

    def _reopen_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.ocr.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _parse_date(self, date_str):
        if not date_str:
            return False
        from datetime import datetime
        date_str = str(date_str).strip().replace('/', '-')
        for fmt in ['%d-%m-%Y', '%Y-%m-%d', '%d-%m-%y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return False

    def _find_country(self, code):
        """Recherche un pays par code ISO alpha-2 ou alpha-3."""
        if not code:
            return None
        code = str(code).upper().strip()
        country = self.env['res.country'].search([('code', '=', code)], limit=1)
        if country:
            return country
        alpha2 = _ALPHA3_TO_ALPHA2.get(code)
        if alpha2:
            return self.env['res.country'].search([('code', '=', alpha2)], limit=1)
        return None

    # ── Bus notifications ──────────────────────────────────────────────

    def _notify_progress(self, cr, uid, wizard_id, message, done=False):
        """Envoie une notification de progression via bus.bus."""
        try:
            env = api.Environment(cr, uid, {})
            user = env['res.users'].browse(uid)
            env['bus.bus']._sendone(
                user.partner_id,
                'hr_ocr/progress',
                {
                    'wizard_id': wizard_id,
                    'message': message,
                    'done': done,
                }
            )
            cr.commit()
        except Exception:
            _logger.debug("Bus notification failed: %s", message)

    # ── Auto-détection ─────────────────────────────────────────────────

    def _detect_document_type(self, file_content, filename, progress):
        """Détection automatique du type de document.

        Stratégie :
        1. Essayer fastmrz → passeport (TD3) ou CIN (TD1)
        2. Si MRZ absente → analyser présence de labels arabes d'acte de naissance
        3. Fallback : retourner 'auto' (inconnu)
        """
        progress("Détection du type de document...")

        # ── 1. Tentative MRZ ──────────────────────────────────────────
        try:
            from .mrz_engine import _file_to_cv2, _process_with_fastmrz
            img = _file_to_cv2(file_content, filename)
            raw = _process_with_fastmrz(img)

            if raw.get('status') == 'SUCCESS':
                mrz_type = raw.get('mrz_type', '')
                doc_code = str(raw.get('document_code', '')).upper()
                if 'TD3' in mrz_type or doc_code.startswith('P'):
                    progress("→ Passeport détecté (MRZ TD3)")
                    return 'passport'
                else:
                    progress("→ Carte d'identité détectée (MRZ TD1)")
                    return 'id_card'
        except Exception as e:
            _logger.debug("MRZ auto-detect failed: %s", e)

        # ── 2. Tentative acte de naissance (labels arabes) ────────────
        try:
            from .ocr_engine import (
                _load_image_from_bytes, _normalize_size, _preprocess,
                _segment_regions, _ocr_all_regions, _find_label, LABELS,
            )
            img = _load_image_from_bytes(file_content, filename)
            img = _normalize_size(img)
            gray, clean = _preprocess(img)
            regions = _segment_regions(clean, gray)
            _ocr_all_regions(regions)

            _, score_nom = _find_label(regions, LABELS["nom_prenom"]["target"])
            _, score_acte = _find_label(regions, LABELS["numero_acte"]["target"])
            best = max(score_nom, score_acte)

            if best >= 0.5:
                progress(f"→ Acte de naissance détecté (confiance {best:.0%})")
                return 'birth_certificate'
        except Exception as e:
            _logger.debug("Birth cert auto-detect failed: %s", e)

        progress("→ Type indéterminé, traitement passeport par défaut")
        return 'auto'   # inconnu

    # ── OCR Thread ─────────────────────────────────────────────────────

    def action_analyze(self):
        """Lance l'analyse OCR en arrière-plan."""
        self.ensure_one()

        if not self.document_file:
            raise UserError(_("Veuillez sélectionner un document."))
        if not self._check_file_extension(self.document_filename):
            raise UserError(_(
                "Format non supporté.\nFormats acceptés: PDF, PNG, JPG"))

        self.write({'state': 'processing', 'validation_errors': False})

        wizard_id = self.id
        uid = self.env.uid
        dbname = self.env.cr.dbname
        doc_type = self.document_type
        file_content = base64.b64decode(self.document_file)
        filename = self.document_filename or 'document.pdf'

        thread = threading.Thread(
            target=self._run_ocr_thread,
            args=(dbname, uid, wizard_id, doc_type, file_content, filename),
            daemon=True,
        )
        thread.start()

        return self._reopen_wizard()

    def _run_ocr_thread(self, dbname, uid, wizard_id,
                        doc_type, file_content, filename):
        """Thread d'arrière-plan pour le traitement OCR."""
        registry = self.env.registry
        try:
            with registry.cursor() as new_cr:
                self._do_ocr(new_cr, uid, wizard_id,
                             doc_type, file_content, filename)
        except Exception as e:
            _logger.exception("Erreur thread OCR")
            try:
                with registry.cursor() as err_cr:
                    env = api.Environment(err_cr, uid, {})
                    wizard = env['hr.ocr.wizard'].browse(wizard_id)
                    if wizard.exists():
                        wizard.write({
                            'state': 'error',
                            'validation_errors': str(e),
                        })
                    self._notify_progress(
                        err_cr, uid, wizard_id,
                        f"ERREUR: {e}", done=True)
            except Exception:
                _logger.exception("Erreur notification d'erreur")

    def _do_ocr(self, cr, uid, wizard_id,
                doc_type, file_content, filename):
        """Exécute l'OCR avec notifications de progression."""
        env = api.Environment(cr, uid, {})
        wizard = env['hr.ocr.wizard'].browse(wizard_id)

        def progress(msg):
            self._notify_progress(cr, uid, wizard_id, msg)

        progress(f"Traitement : {filename}")

        # ── Auto-détection ────────────────────────────────────────────
        is_auto = (doc_type == 'auto')
        if is_auto:
            doc_type = self._detect_document_type(file_content, filename, progress)
            if doc_type == 'auto':
                doc_type = 'passport'   # fallback ultime
            wizard.write({'document_type': doc_type, 'is_auto_detected': True})
            cr.commit()

        # ── Traitement ────────────────────────────────────────────────
        if doc_type == 'birth_certificate':
            result = self._process_birth_certificate(
                file_content, filename, progress)
        else:
            result = self._process_mrz(
                file_content, filename, doc_type, progress)

        progress("Enregistrement des résultats...")

        vals = self._map_results(result, doc_type)
        vals['state'] = 'preview'
        vals['ocr_raw_text'] = json.dumps(
            result, indent=2, ensure_ascii=False)

        wizard.write(vals)
        cr.commit()

        progress("Extraction terminée !")
        self._notify_progress(cr, uid, wizard_id, "", done=True)

    # ── Engines ────────────────────────────────────────────────────────

    def _process_birth_certificate(self, file_content, filename, progress):
        from .ocr_engine import process_birth_certificate

        progress("Chargement de l'image...")
        progress("Prétraitement et segmentation...")
        result = process_birth_certificate(file_content, filename)
        progress(f"Nom : {result.get('name_fr') or result.get('name_ar') or '?'}")
        return result

    def _process_mrz(self, file_content, filename, doc_type, progress):
        from .mrz_engine import process_mrz_document

        result = process_mrz_document(
            file_content, filename, doc_type,
            on_progress=progress,
        )
        return result

    # ── Mapping résultats → champs wizard ──────────────────────────────

    def _map_results(self, result, doc_type):
        """Mappe le dict résultat vers les champs wizard."""
        vals = {}

        if doc_type == 'birth_certificate':
            vals['extracted_name_fr'] = result.get('name_fr', '')
            vals['extracted_name_ar'] = result.get('name_ar', '')
            vals['extracted_birth_date'] = self._parse_date(
                result.get('birth_date'))
            vals['extracted_birth_place'] = result.get('birth_place', '')
            vals['extracted_act_number'] = result.get('act_number', '')
            vals['extracted_father_name'] = result.get('father_name', '')
            vals['extracted_mother_name'] = result.get('mother_name', '')

        else:
            # MRZ : passeport, CIN, permis
            vals['extracted_name_fr'] = result.get('name_fr', '')
            vals['extracted_birth_date'] = self._parse_date(
                result.get('birth_date'))
            vals['extracted_document_number'] = result.get(
                'document_number', '')
            vals['extracted_nationality'] = result.get('nationality', '')
            vals['extracted_expiry_date'] = self._parse_date(
                result.get('expiry_date'))
            vals['extracted_mrz_text'] = result.get('mrz_text', '')
            vals['doc_side'] = result.get('side', 'recto')

            sex = result.get('sex', '')
            if sex == 'M':
                vals['extracted_gender'] = 'male'
            elif sex == 'F':
                vals['extracted_gender'] = 'female'

            if result.get('status') != 'SUCCESS':
                vals['validation_errors'] = result.get(
                    'status_message', 'Extraction incomplète')

        return vals

    # ── Actions utilisateur ────────────────────────────────────────────

    def action_back(self):
        self.write({'state': 'upload'})
        return self._reopen_wizard()

    def _get_algeria(self):
        """Retourne le record res.country pour l'Algérie."""
        return self.env['res.country'].search([('code', '=', 'DZ')], limit=1)

    def action_validate(self):
        """Valider et appliquer les données extraites à la fiche employé."""
        self.ensure_one()

        if not self.employee_id:
            raise UserError(_("Aucun employé sélectionné."))

        vals = {}

        # ── Champ commun à tous les documents : nom français ──────────
        if self.extracted_name_fr:
            vals['name'] = self.extracted_name_fr
            # Détecter automatiquement nom/prénom depuis la convention casse
            nom, prenom = self.env['hr.employee']._compute_nom_prenom(
                self.extracted_name_fr
            )
            if nom:
                vals['nom_famille'] = nom
            if prenom:
                vals['prenom'] = prenom

        if self.document_type == 'birth_certificate':
            # ── Acte de naissance ──────────────────────────────────────
            if self.extracted_birth_date:
                vals['birthday'] = self.extracted_birth_date
            if self.extracted_birth_place:
                vals['place_of_birth'] = self.extracted_birth_place
            if self.extracted_name_ar:
                vals['name_ar'] = self.extracted_name_ar
            if self.extracted_act_number:
                vals['acte_naissance_num'] = self.extracted_act_number
            if self.extracted_father_name:
                vals['prenom_pere'] = self.extracted_father_name
            if self.extracted_mother_name:
                vals['nom_prenom_mere'] = self.extracted_mother_name
            # Pays de naissance = Algérie (document algérien)
            dz = self._get_algeria()
            if dz:
                vals['country_of_birth'] = dz.id

        else:
            # ── MRZ : passeport / CIN / permis ────────────────────────
            if self.extracted_birth_date:
                vals['birthday'] = self.extracted_birth_date
            if self.extracted_gender:
                vals['sex'] = self.extracted_gender

            # Nationalité : code alpha-3 MRZ → pays Odoo
            if self.extracted_nationality:
                country = self._find_country(self.extracted_nationality)
                if country:
                    vals['country_id'] = country.id

            if self.document_type == 'passport':
                if self.extracted_document_number:
                    vals['passport_id'] = self.extracted_document_number
                if self.extracted_expiry_date:
                    vals['pi_date_expiration'] = self.extracted_expiry_date

            elif self.document_type == 'id_card':
                if self.extracted_document_number:
                    vals['identification_id'] = self.extracted_document_number
                if self.extracted_expiry_date:
                    vals['pi_date_expiration'] = self.extracted_expiry_date
                # La CIN est algérienne → pays de naissance = Algérie
                dz = self._get_algeria()
                if dz:
                    vals['country_of_birth'] = dz.id

            elif self.document_type == 'driver_license':
                if self.extracted_document_number:
                    vals['identification_id'] = self.extracted_document_number
                if self.extracted_expiry_date:
                    vals['pi_date_expiration'] = self.extracted_expiry_date

        if vals:
            self.employee_id.write(vals)

        # Sauvegarder le document en pièce jointe
        if self.document_file:
            attachment_name = self.document_filename or 'Document OCR'
            self.env['ir.attachment'].create({
                'name': attachment_name,
                'type': 'binary',
                'datas': self.document_file,
                'res_model': 'hr.employee',
                'res_id': self.employee_id.id,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Succès'),
                'message': _('Informations appliquées à la fiche employé.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
