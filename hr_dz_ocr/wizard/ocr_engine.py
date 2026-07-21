"""
Moteur OCR local pour actes de naissance algeriens.
Pipeline OpenCV + Tesseract : projection-based segmentation.
"""

import logging
import os
import re
import tempfile

import cv2
import numpy as np
import pytesseract
from difflib import SequenceMatcher
from pdf2image import convert_from_path

_logger = logging.getLogger(__name__)

TARGET_WIDTH = 2480  # A4 @ 300 DPI
LINE_GAP = 3

LABELS = {
    "nom_prenom": {
        "target": "المسمى",
    },
    "numero_acte": {
        "target": "رقمالشهادة",
    },
    "lieu_naissance": {
        "target": "ولدت",
    },
    "filiation": {
        # "ابن (ة)" → normalisé : "ابن"
        "target": "ابن",
    },
}


# ── Image loading ──────────────────────────────────────────────────────

def _load_image_from_bytes(file_content, filename, dpi=300):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name
        try:
            pages = convert_from_path(tmp_path, dpi=dpi)
            return cv2.cvtColor(np.array(pages[0]), cv2.COLOR_RGB2BGR)
        finally:
            os.unlink(tmp_path)
    else:
        arr = np.frombuffer(file_content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Impossible de décoder l'image '{filename}'")
        return img


def _normalize_size(img, target_width=TARGET_WIDTH):
    h, w = img.shape[:2]
    if w < target_width:
        scale = target_width / w
        img = cv2.resize(img, (target_width, int(h * scale)),
                         interpolation=cv2.INTER_CUBIC)
    return img


# ── Preprocessing ──────────────────────────────────────────────────────

def _preprocess(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary_inv = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary_inv = cv2.morphologyEx(binary_inv, cv2.MORPH_CLOSE, close_k)

    nb_comp, labels_map, stats, _ = cv2.connectedComponentsWithStats(
        binary_inv, 8)
    clean = np.zeros_like(binary_inv)
    for i in range(1, nb_comp):
        area = stats[i, cv2.CC_STAT_AREA]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        ch = stats[i, cv2.CC_STAT_HEIGHT]
        if area > 60 and (cw > 8 or ch > 8):
            clean[labels_map == i] = 255
    return gray, clean


# ── Segmentation ───────────────────────────────────────────────────────

def _find_lines(binary, min_h=10):
    h, w = binary.shape
    margin = w // 6
    center = binary[:, margin:w - margin]
    hp = np.sum(center, axis=1)
    lines = []
    in_line = False
    y_start = 0
    gap = 0
    for y, val in enumerate(hp):
        if val > 0:
            if not in_line:
                y_start = y
                in_line = True
            gap = 0
        else:
            if in_line:
                gap += 1
                if gap > LINE_GAP:
                    y_end = y - gap
                    if y_end - y_start >= min_h:
                        lines.append((y_start, y_end))
                    in_line = False
                    gap = 0
    if in_line:
        y_end = len(hp) - 1
        if y_end - y_start >= min_h:
            lines.append((y_start, y_end))
    return lines


def _find_words_in_line(binary_line, min_w=8):
    vp = np.sum(binary_line, axis=0)
    gaps = []
    in_gap = False
    gap_start = 0
    for x, val in enumerate(vp):
        if val == 0:
            if not in_gap:
                gap_start = x
                in_gap = True
        else:
            if in_gap:
                gl = x - gap_start
                if gl >= 2:
                    gaps.append(gl)
                in_gap = False
    cut = 5
    if gaps:
        sg = sorted(gaps)
        for i in range(len(sg) - 1):
            if sg[i + 1] >= sg[i] * 1.5 and sg[i] >= 3:
                cut = sg[i] + 1
                break
    words = []
    start = -1
    cnt = 0
    for x, val in enumerate(vp):
        if val != 0:
            cnt = 0
        if val != 0 and start == -1:
            start = x
        if val == 0 and start != -1:
            cnt += 1
            if cnt >= cut:
                x_end = x - cnt
                if x_end - start >= min_w:
                    words.append((start, x_end))
                cnt = 0
                start = -1
    if start != -1:
        x_end = len(vp) - 1
        if x_end - start >= min_w:
            words.append((start, x_end))
    return words


def _segment_regions(clean, gray):
    lines = _find_lines(clean)
    regions = []
    pad_x, pad_y = 12, 10
    for y1, y2 in lines:
        line_bin = clean[y1:y2, :]
        words = _find_words_in_line(line_bin)
        for x1, x2 in words:
            w = x2 - x1
            h = y2 - y1
            cy1 = max(0, y1 - pad_y)
            cy2 = min(gray.shape[0], y2 + pad_y)
            cx1 = max(0, x1 - pad_x)
            cx2 = min(gray.shape[1], x2 + pad_x)
            crop = gray[cy1:cy2, cx1:cx2]
            regions.append({"x": x1, "y": y1, "w": w, "h": h, "crop": crop})
    regions.sort(key=lambda r: (r["y"], r["x"]))
    return regions


def _detect_regions(dilated, gray, min_w=25, min_h=12, max_w=800, max_h=120):
    contours, _ = cv2.findContours(
        dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if min_w <= w <= max_w and min_h <= h <= max_h:
            pad_x, pad_y = 12, 10
            y1 = max(0, y - pad_y)
            y2 = min(gray.shape[0], y + h + pad_y)
            x1 = max(0, x - pad_x)
            x2 = min(gray.shape[1], x + w + pad_x)
            crop = gray[y1:y2, x1:x2]
            regions.append({"x": x, "y": y, "w": w, "h": h, "crop": crop})
    regions.sort(key=lambda r: (r["y"], r["x"]))
    return regions


# ── OCR ────────────────────────────────────────────────────────────────

def _ocr_once(crop_gray, lang, psm):
    _, bw_inv = cv2.threshold(
        crop_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    nb, labels, stats, _ = cv2.connectedComponentsWithStats(bw_inv, 8)
    clean_inv = np.zeros_like(bw_inv)
    for i in range(1, nb):
        if stats[i, cv2.CC_STAT_AREA] > 25:
            clean_inv[labels == i] = 255
    padded = cv2.copyMakeBorder(
        255 - clean_inv, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)
    config = f"--oem 3 --psm {psm} -l {lang}"
    text = pytesseract.image_to_string(padded, config=config).strip()
    for ch in ["\n", "\f", "\r"]:
        text = text.replace(ch, "")
    return text.strip()


def _ocr_crop(crop, lang="ara", psm=7):
    if crop is None or crop.size == 0:
        return ""
    h, w = crop.shape[:2]
    scale = max(1, 80 // max(h, 1))
    if scale > 1:
        crop = cv2.resize(crop, (w * scale, h * scale),
                          interpolation=cv2.INTER_LANCZOS4)
    t1 = _ocr_once(crop, lang, psm)
    t2 = _ocr_once(cv2.GaussianBlur(crop, (3, 3), 0), lang, psm)
    if not t1:
        return t2
    if not t2:
        return t1
    if len(t2) <= len(t1):
        return t2
    return t1


def _ocr_text_roi(roi_gray, lang="eng", psm=6, whitelist=None):
    if roi_gray is None or roi_gray.size == 0:
        return ""
    h, w = roi_gray.shape[:2]
    scale = max(1, 140 // max(h, 1))
    if scale > 1:
        roi_gray = cv2.resize(roi_gray, (w * scale, h * scale),
                              interpolation=cv2.INTER_LANCZOS4)
    _, bw = cv2.threshold(roi_gray, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    padded = cv2.copyMakeBorder(bw, 20, 20, 20, 20,
                                cv2.BORDER_CONSTANT, value=255)
    config = f"--oem 3 --psm {psm} -l {lang}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    text = pytesseract.image_to_string(padded, config=config)
    return text.strip()


# ── Helpers ────────────────────────────────────────────────────────────

def _normalize_label(text):
    text = text.replace(".", "").replace("(", "").replace(")", "")
    text = text.replace("[", "").replace("]", "").replace(" ", "").strip()
    return text


def _similarity(a, b):
    clean_a = _normalize_label(a)
    clean_b = _normalize_label(b)
    if len(clean_a) < 2 or len(clean_b) < 2:
        return 0.0
    return SequenceMatcher(None, clean_a, clean_b).ratio()


def _clean_arabic(text):
    for ch in [".", "\u0660", "\u2026", "\u0640", ":", ";",
               "(", ")", "[", "]", "\u00ab", "\u00bb", "|",
               "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
               "\u0660", "\u0661", "\u0662", "\u0663", "\u0664",
               "\u0665", "\u0666", "\u0667", "\u0668", "\u0669"]:
        text = text.replace(ch, "")
    result = " ".join(text.split()).strip(" /-")
    has_arabic = any("\u0600" <= c <= "\u06FF" for c in result)
    return result if has_arabic else ""


def _extract_date_from_text(text):
    m = re.search(
        r'(\d{1,4})\s*[/\-\.]\s*(\d{1,2})\s*[/\-\.]\s*(\d{1,4})', text)
    if m:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if len(a) == 4:
            return f"{c.zfill(2)}/{b.zfill(2)}/{a}"
        if len(c) == 4:
            return f"{a.zfill(2)}/{b.zfill(2)}/{c}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        if digits.startswith("19") or digits.startswith("20"):
            return f"{digits[6:8]}/{digits[4:6]}/{digits[0:4]}"
        return f"{digits[:2]}/{digits[2:4]}/{digits[4:8]}"
    return ""


def _ocr_all_regions(regions, lang="ara", psm=7):
    for r in regions:
        if "ocr_cache" not in r:
            r["ocr_cache"] = {}
        key = f"{lang}:{psm}"
        if key not in r["ocr_cache"]:
            r["ocr_cache"][key] = _ocr_crop(r["crop"], lang=lang, psm=psm)
        r["ocr"] = r["ocr_cache"][key]


def _ocr_cached(region, lang, psm):
    if "ocr_cache" not in region:
        region["ocr_cache"] = {}
    key = f"{lang}:{psm}"
    if key not in region["ocr_cache"]:
        region["ocr_cache"][key] = _ocr_crop(region["crop"], lang=lang, psm=psm)
    return region["ocr_cache"][key]


def _group_by_line(regions, max_dy=20):
    regions_sorted = sorted(regions, key=lambda r: (r["y"], r["x"]))
    lines = []
    for r in regions_sorted:
        placed = False
        for line in lines:
            if abs(r["y"] - line[0]["y"]) <= max_dy:
                line.append(r)
                placed = True
                break
        if not placed:
            lines.append([r])
    for line in lines:
        line.sort(key=lambda r: r["x"])
    return lines


def _find_label(regions, target, threshold=0.6):
    best = None
    best_score = 0
    lines = _group_by_line(regions, max_dy=25)
    for line in lines:
        for i, r in enumerate(line):
            score = _similarity(r["ocr"], target)
            if score > best_score and score >= threshold:
                best_score = score
                best = r
            for j in range(i + 1, len(line)):
                r2 = line[j]
                if r2["x"] - (r["x"] + r["w"]) >= 80:
                    break
                combined = r["ocr"] + r2["ocr"]
                score2 = _similarity(combined, target)
                if score2 > best_score and score2 >= threshold:
                    best_score = score2
                    best = r2
    return best, best_score


def _get_values_left(regions, label_r, max_dy=30, min_w=15):
    vals = [
        r for r in regions
        if abs(r["y"] - label_r["y"]) < max_dy
        and r["x"] + r["w"] < label_r["x"] - 5
        and r["w"] >= min_w
        and r is not label_r
    ]
    vals.sort(key=lambda v: -v["x"])
    return vals


def _get_values_below(regions, label_r, max_dy=80, max_dx=150):
    vals = [
        r for r in regions
        if r["y"] > label_r["y"]
        and r["y"] - label_r["y"] < max_dy
        and abs(r["x"] - label_r["x"]) < max_dx
        and r is not label_r
    ]
    vals.sort(key=lambda v: v["y"])
    return vals


def _find_latin_name(gray, clean):
    h, w = gray.shape
    y_start = int(h * 0.80)
    gray_bot = gray[y_start:h, :]
    clean_bot = clean[y_start:h, :]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 5))
    dilated_bot = cv2.dilate(clean_bot, kernel, iterations=1)
    regions = _detect_regions(
        dilated_bot, gray_bot, min_w=25, min_h=10, max_w=600, max_h=80)
    for r in regions:
        text = _ocr_crop(r["crop"], lang="eng", psm=7)
        r["ocr"] = text
        ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
        r["is_latin"] = ascii_alpha >= 2
    family = None
    for r in regions:
        if not r["is_latin"]:
            continue
        ct = "".join(c for c in r["ocr"] if c.isalpha())
        if ct.isascii() and ct.isupper() and len(ct) >= 4:
            family = r
            break
    if not family:
        return ""
    same_line = [
        r for r in regions
        if abs(r["y"] - family["y"]) < 20 and r["is_latin"]
    ]
    same_line.sort(key=lambda r: r["x"])
    words = []
    for r in same_line:
        w = r["ocr"].replace(".", "").strip()
        for ch in ["_", ",", ";", "'"]:
            w = w.replace(ch, "")
        w = w.strip()
        if not w:
            continue
        if w[0].isupper():
            words.append(w)
    return " ".join(words)


# ── Extraction fields ──────────────────────────────────────────────────

def _extract_name(regions):
    label, score = _find_label(regions, LABELS["nom_prenom"]["target"])
    if not label:
        return ""
    vals = _get_values_left(regions, label)
    parts = []
    for v in vals:
        t = _ocr_cached(v, lang="ara", psm=7)
        ct = _clean_arabic(t)
        if ct:
            parts.append(ct)
    return " ".join(parts)


def _extract_act_number(regions):
    label, score = _find_label(regions, LABELS["numero_acte"]["target"])
    if not label:
        return "", None
    candidates = (_get_values_left(regions, label, max_dy=40) +
                  _get_values_below(regions, label, max_dy=120, max_dx=300))
    for v in candidates:
        t = _ocr_cached(v, lang="eng", psm=7)
        digits = "".join(c for c in t if c.isdigit())
        if len(digits) >= 3:
            return digits, v
    return "", None


def _extract_birth_date(regions, gray, numero_region):
    if not numero_region:
        return ""
    # Chercher dans les regions segmentees
    date_candidates = [
        r for r in regions
        if r["y"] > numero_region["y"]
        and r["y"] - numero_region["y"] < 150
        and abs(r["x"] - numero_region["x"]) < 400
        and r is not numero_region
    ]
    date_candidates.sort(key=lambda v: v["y"])
    for v in date_candidates:
        t = _ocr_cached(v, lang="eng", psm=7)
        m = re.search(
            r'(\d{1,2})\s*[/\-\.]\s*(\d{1,2})\s*[/\-\.]\s*(\d{2,4})', t)
        if m:
            return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        digits = "".join(c for c in t if c.isdigit())
        if len(digits) >= 8:
            return f"{digits[:2]}/{digits[2:4]}/{digits[4:8]}"

    # Fallback: OCR d'une zone large sous le numero
    h_img, w_img = gray.shape
    x = numero_region["x"]
    y = numero_region["y"]
    w = numero_region["w"]
    h = numero_region["h"]
    x1 = max(0, x - 800)
    x2 = min(w_img, x + w + 300)
    y1 = min(h_img, y + h + 10)
    y2 = min(h_img, y + h + 420)
    roi = gray[y1:y2, x1:x2]
    for psm in [6, 11, 7]:
        t = _ocr_text_roi(roi, lang="eng", psm=psm,
                          whitelist="0123456789/-.")
        d = _extract_date_from_text(t)
        if d:
            return d
    return ""


def _extract_birth_place(regions):
    label, score = _find_label(
        regions, LABELS["lieu_naissance"]["target"], threshold=0.4)
    if not label:
        return ""
    vals = _get_values_left(regions, label, max_dy=30, min_w=15)
    parts = []
    for v in vals:
        t = _ocr_cached(v, lang="ara", psm=7)
        ct = _clean_arabic(t)
        if ct and len(ct) > 1:
            parts.append(ct)
    lieu = " ".join(parts)
    # Fallback: valeur fusionnee dans le label
    if not lieu and label["w"] > 200:
        raw = label["ocr"]
        for pat in ["ولد", "ولدت", "ولدزت", "بلدرت",
                     "(ت)", "بـ", "ب", "د "]:
            raw = raw.replace(pat, "")
        raw = raw.replace(")", "").replace("(", "")
        ct = _clean_arabic(raw)
        if ct:
            lieu = ct
    return lieu


# ── Filiation ──────────────────────────────────────────────────────────

# Mots arabes courants sur les actes de naissance qui ne sont pas des noms
_NON_NAME_AR = {
    "مهنته", "مهنتـه", "عمره", "بلدية", "ولاية",   # ligne père
    "مهنتها", "عمرها",                               # ligne mère
    "الجزائر", "الساكنين", "الساكنون",
}


def _collect_arabic_name(vals):
    """Collecte les tokens arabes d'une liste de régions jusqu'au premier
    token non-nom (champ administratif ou valeur numérique)."""
    parts = []
    for v in vals:
        t = _ocr_cached(v, lang="ara", psm=7)
        ct = _clean_arabic(t)
        if not ct or len(ct) < 2:
            continue
        if re.search(r'\d', ct):
            break   # atteint la valeur d'âge → fin du nom
        if ct in _NON_NAME_AR:
            break   # atteint un champ administratif
        parts.append(ct)
    return " ".join(parts)


def _extract_filiation(regions):
    """Extraire prénom du père et nom+prénom de la mère.

    Sur l'acte de naissance algérien :
      - Ligne père : ابن (ة) [prénom_père] عمره … مهنته …
      - Ligne mère : و. [nom_mère prénom_mère] عمرها … مهنتها …
    Les valeurs sont à GAUCHE du label (écriture RTL).
    """
    label, _ = _find_label(regions, LABELS["filiation"]["target"], threshold=0.45)
    if not label:
        return "", ""

    # ── Prénom du père ──────────────────────────────────────────────────
    father_vals = _get_values_left(regions, label, max_dy=25, min_w=20)
    father_name = _collect_arabic_name(father_vals)

    # ── Nom + prénom de la mère : ligne juste en dessous de « ابن » ────
    father_y = label["y"]
    line_h = max(label["h"], 15)

    # Toutes les régions situées entre 0.5 et 3.5 hauteurs de ligne en dessous
    below = [
        r for r in regions
        if line_h * 0.5 < (r["y"] - father_y) < line_h * 3.5
        and r["w"] >= 20
    ]
    if not below:
        return father_name, ""

    # Accroche sur le y minimal = première ligne sous la ligne père
    snap_y = min(r["y"] for r in below)
    mother_line = sorted(
        [r for r in below if abs(r["y"] - snap_y) < 25],
        key=lambda r: -r["x"],   # RTL : le plus à droite = premier lu
    )

    # Ignorer le connecteur « و » en tête de ligne
    mother_vals = [
        v for v in mother_line
        if _clean_arabic(_ocr_cached(v, "ara", 7)) not in {"", "و"}
    ]
    mother_name = _collect_arabic_name(mother_vals)

    return father_name, mother_name


# ── Point d'entree principal ───────────────────────────────────────────

def process_birth_certificate(file_content, filename):
    """Traite un acte de naissance et retourne les donnees extraites.

    Args:
        file_content (bytes): contenu brut du fichier (PDF ou image)
        filename (str): nom du fichier (pour detecter le type via extension)

    Returns:
        dict: {name_ar, name_fr, act_number, birth_date, birth_place}
    """
    _logger.info("OCR acte de naissance: %s", filename)

    img = _load_image_from_bytes(file_content, filename)
    img = _normalize_size(img)
    gray, clean = _preprocess(img)
    regions = _segment_regions(clean, gray)
    _logger.info("Segmentation: %d regions", len(regions))

    _ocr_all_regions(regions)

    name_ar = _extract_name(regions)
    _logger.info("Nom arabe: %s", name_ar)

    name_fr = _find_latin_name(gray, clean)
    _logger.info("Nom latin: %s", name_fr)

    act_number, numero_region = _extract_act_number(regions)
    _logger.info("Numero acte: %s", act_number)

    birth_date = _extract_birth_date(regions, gray, numero_region)
    _logger.info("Date naissance: %s", birth_date)

    birth_place = _extract_birth_place(regions)
    _logger.info("Lieu naissance: %s", birth_place)

    father_name, mother_name = _extract_filiation(regions)
    _logger.info("Prenom pere: %s", father_name)
    _logger.info("Nom mere: %s", mother_name)

    return {
        "name_ar": name_ar,
        "name_fr": name_fr,
        "act_number": act_number,
        "birth_date": birth_date,     # format dd/mm/yyyy
        "birth_place": birth_place,
        "father_name": father_name,
        "mother_name": mother_name,
    }
