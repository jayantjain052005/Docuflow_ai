"""
DocuFlow AI - OCR Pipeline Constants
All configuration, keyword lists, and fixed values used across the pipeline.
"""

import os

# ─────────────────────────────────────────────
# OCR MODE SELECTION
# ─────────────────────────────────────────────
# Set via environment variable before starting the application:
#
#   Windows:  set DOCUFLOW_OCR_MODE=dev
#   Linux:    export DOCUFLOW_OCR_MODE=prod
#
#   dev      — ~4  Tesseract calls/image  (fast local testing, < 3s/image)
#   balanced — ~18 Tesseract calls/image  (good quality + speed, < 12s/image)
#   prod     — ~72 Tesseract calls/image  (full exhaustive ensemble)
#
# Defaults to "dev" so developers never accidentally run the full ensemble.
# Always set to "prod" in your production / Docker environment config.

OCR_MODE = os.environ.get("DOCUFLOW_OCR_MODE", "dev").lower().strip()

if OCR_MODE not in ("dev", "balanced", "prod"):
    import warnings
    warnings.warn(
        f"Unknown DOCUFLOW_OCR_MODE='{OCR_MODE}'. Falling back to 'dev'. "
        "Valid options: dev | balanced | prod",
        stacklevel=2,
    )
    OCR_MODE = "dev"

# ─────────────────────────────────────────────
# PER-MODE OCR PARAMETERS
# ─────────────────────────────────────────────
#
# pass count = len(scales) x (len(pipelines) + include_grayscale) x len(psm_modes)
#
#   dev      = 1 x (1+0) x 2 =  2 preprocessing x 2 PSM =  4 calls
#   balanced = 2 x (3+0) x 3 =  6 preprocessing x 3 PSM = 18 calls
#   prod     = 3 x (5+1) x 4 = 18 preprocessing x 4 PSM = 72 calls

_OCR_MODE_CONFIGS: dict[str, dict] = {
    "dev": {
        # Single scale — 2.0x is the sweet spot for most Indian doc scans
        "scales":             [2.0],
        # One pipeline — "standard" (denoise+bilateral+CLAHE+Otsu) works for
        # the majority of decent-quality scans and digital PDFs
        "pipelines":          ["standard"],
        # Include raw grayscale — fast to produce (no binarization) and frequently
        # wins on clean scans / digital PDFs. Gives exactly 4 passes in dev mode.
        "include_grayscale":  True,
        # PSM 6 = assume uniform block of text (best for single-page Indian docs)
        # PSM 3 = fully automatic (fallback)
        "psm_modes":          [6, 3],
        # Deskew is OpenCV-based (fast) but adds ~200ms; skip in dev
        "do_deskew":          False,
        # OSD rotation calls Tesseract internally — very slow on Windows; skip
        "do_rotate":          False,
        # Lower PDF rasterisation resolution speeds up pdfplumber page.to_image()
        "pdf_resolution":     200,
        # Per-call Tesseract wall-clock timeout in seconds
        "timeout_s":          8.0,
        # Stop running more passes once the best score exceeds this threshold.
        # 80 is achievable by pass 1 on a clean scan, saving all remaining passes.
        "early_stop_score":   80.0,
    },
    "balanced": {
        "scales":             [2.0, 1.5],
        "pipelines":          ["standard", "adaptive", "sharpen"],
        "include_grayscale":  False,
        "psm_modes":          [6, 3, 4],
        "do_deskew":          True,
        # OSD still off — adds 1-2s per image; enable only in prod
        "do_rotate":          False,
        "pdf_resolution":     250,
        "timeout_s":          15.0,
        "early_stop_score":   90.0,
    },
    "prod": {
        "scales":             [1.5, 2.0, 2.5],
        "pipelines":          ["standard", "adaptive", "sharpen", "light", "heavy_denoise"],
        "include_grayscale":  True,
        "psm_modes":          [3, 4, 6, 11],
        "do_deskew":          True,
        "do_rotate":          True,
        "pdf_resolution":     300,
        "timeout_s":          30.0,
        "early_stop_score":   95.0,
    },
}

# Active config — all other modules read from here
_ACTIVE_OCR_CFG: dict = _OCR_MODE_CONFIGS[OCR_MODE]

# ── Expose named constants so all existing imports keep working ──
TESSERACT_PSM_MODES:    list[int]   = _ACTIVE_OCR_CFG["psm_modes"]
OCR_RESIZE_FACTORS:     list[float] = _ACTIVE_OCR_CFG["scales"]
PDF_RESOLUTION:         int         = _ACTIVE_OCR_CFG["pdf_resolution"]
OCR_TIMEOUT_S:          float       = _ACTIVE_OCR_CFG["timeout_s"]
OCR_EARLY_STOP_SCORE:   float       = _ACTIVE_OCR_CFG["early_stop_score"]
OCR_DO_DESKEW:          bool        = _ACTIVE_OCR_CFG["do_deskew"]
OCR_DO_ROTATE:          bool        = _ACTIVE_OCR_CFG["do_rotate"]
OCR_PIPELINES:          list[str]   = _ACTIVE_OCR_CFG["pipelines"]
OCR_INCLUDE_GRAYSCALE:  bool        = _ACTIVE_OCR_CFG["include_grayscale"]

# Unchanged across all modes
TESSERACT_OEM_MODE = 3   # LSTM + Legacy
TESSERACT_LANG     = "eng"
MIN_EMBEDDED_TEXT_LENGTH = 40  # chars; below this → treat PDF page as scanned

# ─────────────────────────────────────────────
# PREPROCESSING THRESHOLDS
# ─────────────────────────────────────────────

CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (8, 8)
BILATERAL_D = 9
BILATERAL_SIGMA_COLOR = 75
BILATERAL_SIGMA_SPACE = 75
MORPH_KERNEL_SIZE = (1, 1)
SHARPEN_KERNEL = [
    [0, -1, 0],
    [-1, 5, -1],
    [0, -1, 0],
]

# ─────────────────────────────────────────────
# SCORING WEIGHTS
# ─────────────────────────────────────────────

SCORE_PAN_MATCH = 30
SCORE_AADHAAR_MATCH = 25
SCORE_GSTIN_MATCH = 25
SCORE_KEYWORD_HIT = 8
SCORE_WORD_COUNT_FACTOR = 0.05
SCORE_ALNUM_DENSITY_FACTOR = 0.3
MIN_ACCEPTABLE_OCR_SCORE = 5

# ─────────────────────────────────────────────
# DOCUMENT TYPE LABELS
# ─────────────────────────────────────────────

DOCTYPE_PAN_CARD = "PAN Card"
DOCTYPE_AADHAAR = "Aadhaar Card"
DOCTYPE_ITR_ACK = "ITR Acknowledgement"
DOCTYPE_GST_CERT = "GST Certificate"
DOCTYPE_BANK_STMT = "Bank Statement"
DOCTYPE_SALARY_SLIP = "Salary Slip"
DOCTYPE_INVOICE = "Invoice"
DOCTYPE_FORM16 = "Form 16"
DOCTYPE_CHEQUE = "Cheque"
DOCTYPE_PASSBOOK = "Passbook"
DOCTYPE_BALANCE_SHEET = "Balance Sheet"
DOCTYPE_OTHER = "Other"

ALL_DOC_TYPES = [
    DOCTYPE_PAN_CARD,
    DOCTYPE_AADHAAR,
    DOCTYPE_ITR_ACK,
    DOCTYPE_GST_CERT,
    DOCTYPE_BANK_STMT,
    DOCTYPE_SALARY_SLIP,
    DOCTYPE_INVOICE,
    DOCTYPE_FORM16,
    DOCTYPE_CHEQUE,
    DOCTYPE_PASSBOOK,
    DOCTYPE_BALANCE_SHEET,
    DOCTYPE_OTHER,
]

# ─────────────────────────────────────────────
# CLASSIFICATION KEYWORD MAPS
# Each doc type → list of (keyword, weight) tuples
# ─────────────────────────────────────────────

CLASSIFICATION_KEYWORDS: dict[str, list[tuple[str, int]]] = {
    DOCTYPE_PAN_CARD: [
        ("permanent account number", 20),
        ("income tax department", 15),
        ("pan", 8),
        ("govt. of india", 10),
        ("date of birth", 6),
        ("father", 6),
        ("signature", 4),
    ],
    DOCTYPE_AADHAAR: [
        ("aadhaar", 25),
        ("unique identification", 20),
        ("uidai", 20),
        ("enrolment no", 12),
        ("vid:", 10),
        ("your aadhaar", 10),
        ("government of india", 5),
        ("dob:", 4),
    ],
    DOCTYPE_ITR_ACK: [
        ("acknowledgement", 20),
        ("itr", 15),
        ("income tax return", 20),
        ("assessment year", 15),
        ("ay ", 10),
        ("central processing centre", 12),
        ("cpc", 8),
        ("filed", 8),
        ("refund", 6),
        ("tax payable", 6),
        ("total income", 6),
        ("gross total income", 6),
        ("return of income", 15),
        ("e-filing", 10),
        ("verification", 5),
        ("bangalore", 5),
        ("bengaluru", 5),
    ],
    DOCTYPE_GST_CERT: [
        ("gstin", 25),
        ("goods and services tax", 20),
        ("gst", 10),
        ("registration certificate", 12),
        ("place of business", 10),
        ("taxpayer type", 8),
        ("constitution of business", 8),
        ("date of registration", 8),
        ("gst certificate", 20),
    ],
    DOCTYPE_BANK_STMT: [
        ("statement of account", 20),
        ("account statement", 18),
        ("opening balance", 15),
        ("closing balance", 15),
        ("debit", 10),
        ("credit", 10),
        ("transaction", 10),
        ("ifsc", 8),
        ("branch", 6),
        ("cheque no", 6),
        ("utr", 5),
        ("neft", 5),
        ("rtgs", 5),
        ("imps", 5),
    ],
    DOCTYPE_SALARY_SLIP: [
        ("salary slip", 25),
        ("payslip", 20),
        ("pay slip", 20),
        ("gross salary", 15),
        ("net salary", 15),
        ("basic salary", 12),
        ("hra", 10),
        ("provident fund", 10),
        ("pf", 6),
        ("tds", 8),
        ("employee id", 8),
        ("employee code", 8),
        ("department", 5),
        ("designation", 5),
    ],
    DOCTYPE_INVOICE: [
        ("invoice", 20),
        ("tax invoice", 22),
        ("bill to", 12),
        ("ship to", 8),
        ("invoice no", 15),
        ("invoice date", 12),
        ("amount due", 10),
        ("total amount", 8),
        ("hsn", 8),
        ("sac", 6),
        ("cgst", 8),
        ("sgst", 8),
        ("igst", 8),
    ],
    DOCTYPE_FORM16: [
        ("form 16", 25),
        ("form no. 16", 25),
        ("certificate under section 203", 20),
        ("tds certificate", 18),
        ("tan of deductor", 15),
        ("pan of employee", 15),
        ("salaries", 10),
        ("deductor", 10),
        ("deductee", 10),
        ("quarter", 8),
    ],
    DOCTYPE_CHEQUE: [
        ("pay", 8),
        ("or bearer", 12),
        ("rupees", 6),
        ("account payee", 12),
        ("micr", 10),
        ("ifsc", 8),
        ("cheque", 10),
        ("drawn on", 8),
    ],
    DOCTYPE_PASSBOOK: [
        ("passbook", 20),
        ("savings account", 12),
        ("current account", 12),
        ("account holder", 10),
        ("opening balance", 10),
        ("interest", 6),
        ("nominee", 8),
    ],
    DOCTYPE_BALANCE_SHEET: [
        ("balance sheet", 30),
        ("assets", 14),
        ("liabilities", 14),
        ("equity and liabilities", 20),
        ("current assets", 16),
        ("non-current assets", 16),
        ("current liabilities", 16),
        ("non-current liabilities", 16),
        ("fixed assets", 14),
        ("share capital", 12),
        ("reserves and surplus", 12),
        ("profit and loss", 12),
        ("as at", 6),
    ],
}

# ─────────────────────────────────────────────
# OCR SCORING KEYWORDS (generic Indian docs)
# ─────────────────────────────────────────────

OCR_SCORE_KEYWORDS = [
    "india",
    "government",
    "income",
    "tax",
    "name",
    "father",
    "birth",
    "pan",
    "aadhaar",
    "gst",
    "gstin",
    "account",
    "number",
    "permanent",
    "acknowledgement",
    "itr",
    "assessment",
    "year",
    "salary",
    "invoice",
    "certificate",
    "return",
    "filing",
    "refund",
    "payable",
    "debit",
    "credit",
    "balance",
    "branch",
    "ifsc",
    "cheque",
    "bank",
    "department",
    "employee",
    "form",
    "total",
]

# ─────────────────────────────────────────────
# NAME DETECTION - LABEL ANCHORS
# ─────────────────────────────────────────────

NAME_LABELS = [
    "name",
    "assessee name",
    "applicant name",
    "customer name",
    "employee name",
    "account holder",
    "taxpayer name",
    "name of taxpayer",
    "name of assessee",
    "name of applicant",
    "proprietor name",
    "authorized signatory",
    "full name",
    "registered name",
    "partner name",
    "company name",
]

# Words/phrases that are NOT names (false-positive filter)
NAME_BLACKLIST = {
    "income", "tax", "department", "government", "india", "permanent",
    "account", "number", "return", "acknowledgement", "assessment", "year",
    "receipt", "date", "mobile", "email", "address", "state", "district",
    "pin", "code", "gender", "male", "female", "other", "status", "type",
    "category", "section", "form", "itr", "pan", "gst", "gstin", "tan",
    "cin", "ifsc", "bank", "branch", "debit", "credit", "balance",
    "salary", "designation", "employee", "employer", "deductor", "deductee",
    "challan", "serial", "amount", "total", "gross", "net", "basic",
    "signature", "verification", "certified", "original", "copy",
    "page", "of", "the", "and", "for", "in", "to", "from", "by",
    "central", "processing", "centre", "bangalore", "bengaluru",
    "none", "null", "na", "n/a",
}

# ─────────────────────────────────────────────
# OCR CHARACTER CORRECTIONS
# ─────────────────────────────────────────────

# These are common Tesseract misreads in Indian docs
# Applied selectively based on context (not globally)
DIGIT_CONFUSABLES = {
    "O": "0",
    "o": "0",
    "I": "1",
    "l": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "G": "6",
    "g": "6",
    "Z": "2",
    "z": "2",
}

ALPHA_CONFUSABLES = {
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
    "6": "G",
}
