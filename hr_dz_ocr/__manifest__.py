{
    'name': 'HR DZ OCR - Documents Algériens',
    'version': '19.0.2.0.0',
    'category': 'Human Resources',
    'summary': 'OCR local pour documents administratifs algériens',
    'description': """
        Module OCR pour extraire les informations des documents
        administratifs algériens.

        Documents supportés:
        - Acte de naissance (OpenCV + Tesseract)
        - Passeport (MRZ - fastmrz)
        - Carte d'identité (MRZ - fastmrz)
        - Permis de conduire (MRZ - Tesseract + mrz parser)

        Prérequis système:
        - tesseract-ocr, tesseract-ocr-ara
        - poppler-utils (pour les PDF)
        - mrz.traineddata dans tessdata

        Prérequis Python:
        - opencv-python-headless, pytesseract, pdf2image
        - numpy, Pillow, fastmrz, mrz
    """,
    'author': 'MESSAOUDI ABDERRAOUF',
    'depends': ['hr', 'hr_dz_base', 'bus'],
    'external_dependencies': {
        'python': ['cv2', 'pytesseract', 'pdf2image', 'numpy', 'Pillow',
                   'fastmrz', 'mrz'],
        'bin': ['tesseract'],
    },
    'data': [
        'security/ir.model.access.csv',
        'wizard/hr_ocr_wizard_views.xml',
        'views/hr_employee_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_dz_ocr/static/src/css/ocr_progress.css',
            'hr_dz_ocr/static/src/xml/ocr_progress.xml',
            'hr_dz_ocr/static/src/js/ocr_progress.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
