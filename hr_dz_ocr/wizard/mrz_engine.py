"""
Moteur MRZ pour documents d'identite algeriens.
Passeport + Carte ID : fastmrz (detection auto).
Permis de conduire : Tesseract OCR (lang=mrz) + mrz parser.
"""

import logging
import os
import tempfile

import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_path

_logger = logging.getLogger(__name__)


def _pdf_to_image(file_content, dpi=300):
    """Convertit un PDF (bytes) en image OpenCV."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name
    try:
        pages = convert_from_path(tmp_path, dpi=dpi)
        return cv2.cvtColor(np.array(pages[0]), cv2.COLOR_RGB2BGR)
    finally:
        os.unlink(tmp_path)


def _bytes_to_image(file_content):
    """Decode des bytes image en OpenCV."""
    arr = np.frombuffer(file_content, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Impossible de decoder l'image")
    return img


def _save_tmp_jpg(img):
    """Sauvegarde une image OpenCV en fichier JPG temporaire."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        cv2.imwrite(tmp.name, img)
        return tmp.name


def _file_to_cv2(file_content, filename):
    """Convertit file_content (bytes) en image OpenCV."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        return _pdf_to_image(file_content)
    return _bytes_to_image(file_content)


def _format_date(date_str):
    """Convertit YYYY-MM-DD ou YYMMDD en DD/MM/YYYY."""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    if len(date_str) == 6:
        yy, mm, dd = date_str[:2], date_str[2:4], date_str[4:6]
        year = int(yy)
        prefix = "19" if year > 40 else "20"
        return f"{dd}/{mm}/{prefix}{yy}"
    if "-" in date_str:
        parts = date_str.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return date_str


def _format_name(surname, given_name):
    """Formate nom complet depuis MRZ."""
    parts = []
    if surname:
        parts.append(surname.strip().title())
    if given_name:
        for gn in given_name.strip().split():
            parts.append(gn.title())
    return " ".join(parts)


# ── Passeport / Carte ID (fastmrz) ────────────────────────────────────

def _process_with_fastmrz(img, on_progress=None):
    """Utilise fastmrz pour detecter et parser la MRZ."""
    from fastmrz import FastMRZ

    if on_progress:
        on_progress("Detection de la zone MRZ...")

    fast_mrz = FastMRZ()
    tmp_path = _save_tmp_jpg(img)
    try:
        result = fast_mrz.get_details(tmp_path)
    finally:
        os.unlink(tmp_path)

    if on_progress:
        on_progress(f"MRZ type: {result.get('mrz_type', '?')}")

    return result


# ── Permis de conduire (Tesseract + mrz parser) ───────────────────────

def _extract_mrz_lines_tesseract(img, on_progress=None):
    """Extrait les lignes MRZ du bas de l'image avec Tesseract."""
    if on_progress:
        on_progress("OCR de la zone MRZ (Tesseract)...")

    h = img.shape[0]
    bottom = img[int(h * 0.5):, :]
    gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)

    text = pytesseract.image_to_string(
        gray, config="--oem 3 --psm 6 -l mrz")

    # Filtrer les lignes qui ressemblent a du MRZ (>20 chars, contient <)
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if len(line) >= 25 and "<" in line:
            # Nettoyer : remplacer espaces et caracteres parasites
            cleaned = line.replace(" ", "")
            lines.append(cleaned)

    if on_progress:
        on_progress(f"{len(lines)} lignes MRZ detectees")

    return lines


def _process_driver_license(img, on_progress=None):
    """Traite un permis de conduire via Tesseract + mrz parser."""
    from mrz.checker.td1 import TD1CodeChecker

    lines = _extract_mrz_lines_tesseract(img, on_progress)

    if len(lines) < 3:
        return {"status": "FAILURE", "status_message": "MRZ non detectee"}

    if on_progress:
        on_progress("Parsing MRZ TD1...")

    # Prendre les 3 dernieres lignes (les plus proches du format MRZ)
    mrz_lines = lines[-3:]
    # Padder/tronquer a 30 chars (TD1 standard)
    mrz_lines = [l.ljust(30, "<")[:30] for l in mrz_lines]
    mrz_text = "\n".join(mrz_lines)

    try:
        td1 = TD1CodeChecker(mrz_text)
        f = td1.fields()
        return {
            "mrz_type": "TD1",
            "document_code": f.document_type,
            "issuer_code": f.country,
            "surname": f.surname,
            "given_name": f.name,
            "document_number": f.document_number,
            "nationality_code": f.nationality,
            "birth_date": _format_date(f.birth_date),
            "sex": f.sex,
            "expiry_date": _format_date(f.expiry_date),
            "status": "SUCCESS",
            "mrz_text": mrz_text,
        }
    except Exception as e:
        _logger.warning("Erreur parsing MRZ permis: %s", e)
        return {
            "status": "FAILURE",
            "status_message": f"Erreur parsing MRZ: {e}",
            "mrz_text": mrz_text,
        }


# ── Normalisation du resultat ──────────────────────────────────────────

def _normalize_result(raw, doc_type):
    """Normalise le resultat MRZ en dict standard."""
    if raw.get("status") == "FAILURE" and not raw.get("surname"):
        return raw

    surname = raw.get("surname", "")
    given_name = raw.get("given_name", "")

    return {
        "name_fr": _format_name(surname, given_name),
        "surname": surname,
        "given_name": given_name,
        "birth_date": _format_date(raw.get("birth_date", "")),
        "sex": raw.get("sex", ""),
        "document_number": raw.get("document_number", ""),
        "nationality": raw.get("nationality_code", raw.get("nationality", "")),
        "expiry_date": _format_date(raw.get("expiry_date", "")),
        "issuer": raw.get("issuer_code", raw.get("issuer", "")),
        "mrz_type": raw.get("mrz_type", ""),
        "document_type": doc_type,
        "status": raw.get("status", "SUCCESS"),
        "mrz_text": raw.get("mrz_text", ""),
        # 'recto' si MRZ détectée, 'verso' si MRZ absente (CIN verso typiquement)
        "side": "verso" if raw.get("status") == "FAILURE" else "recto",
    }


# ── Point d'entree ─────────────────────────────────────────────────────

def process_mrz_document(file_content, filename, doc_type, on_progress=None):
    """Traite un document MRZ et retourne les donnees extraites.

    Args:
        file_content (bytes): contenu brut du fichier
        filename (str): nom du fichier
        doc_type (str): 'passport', 'id_card', ou 'driver_license'
        on_progress (callable): callback(message) pour progression

    Returns:
        dict normalisé avec les champs extraits
    """
    cb = on_progress or (lambda msg: None)

    cb("Chargement de l'image...")
    img = _file_to_cv2(file_content, filename)
    _logger.info("MRZ document: %s (%dx%d)", filename,
                 img.shape[1], img.shape[0])

    if doc_type == "driver_license":
        raw = _process_driver_license(img, on_progress=cb)
    else:
        raw = _process_with_fastmrz(img, on_progress=cb)

    cb("Extraction des donnees...")
    result = _normalize_result(raw, doc_type)

    if result.get("status") == "SUCCESS":
        cb(f"OK: {result.get('name_fr', '?')}")
    else:
        cb(f"Echec: {result.get('status_message', 'inconnu')}")

    _logger.info("MRZ resultat: %s", result)
    return result
