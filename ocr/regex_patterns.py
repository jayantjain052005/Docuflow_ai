"""
DocuFlow AI - Regex Patterns for Indian Financial/Legal Documents

All patterns are designed to:
- Handle OCR corruption (common character substitutions)
- Be tolerant of spacing/formatting variations
- Prefer precision over recall for IDs (to avoid false positives)
- Use named groups for easy extraction
"""

import re
from typing import Optional

# ─────────────────────────────────────────────
# PAN CARD
# Format: AAAAA9999A (5 alpha, 4 digits, 1 alpha)
# OCR corruptions: O↔0, I↔1, S↔5, B↔8
# ─────────────────────────────────────────────

# Strict: exactly valid PAN format (used after correction)
PAN_STRICT = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b')

# Tolerant: allows O↔0, I↔1 confusables in digit positions
PAN_TOLERANT = re.compile(
    r'\b([A-Z]{5}[0-9OoIlBGSZ]{4}[A-Z])\b',
    re.IGNORECASE
)

# Context-aware: looks for PAN preceded/followed by label
PAN_WITH_LABEL = re.compile(
    r'(?:pan\s*(?:no\.?|number|card)?[\s:—\-]+)([A-Z0-9OoIlBGSZ]{10})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# AADHAAR
# Format: 4-4-4 digits (12 digits total)
# ─────────────────────────────────────────────

AADHAAR_FORMATTED = re.compile(r'\b(\d{4}[\s\-]\d{4}[\s\-]\d{4})\b')
AADHAAR_PLAIN = re.compile(r'\b(\d{12})\b')
AADHAAR_WITH_LABEL = re.compile(
    r'(?:aadhaar|uid|enrolment)[\s\w]*?(?:no\.?|number)?[\s:—\-]+(\d[\d\s\-]{10,14}\d)',
    re.IGNORECASE
)
# Masked Aadhaar (e.g. XXXX XXXX 1234)
AADHAAR_MASKED = re.compile(r'\b[Xx*]{4}[\s\-][Xx*]{4}[\s\-](\d{4})\b')

# ─────────────────────────────────────────────
# GSTIN
# Format: 2 digits + 5 alpha + 4 digits + 1 alpha + 1 alpha/digit + Z + digit/alpha
# ─────────────────────────────────────────────

GSTIN_STRICT = re.compile(
    r'\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b'
)
GSTIN_TOLERANT = re.compile(
    r'\b([0-9OoIl]{2}[A-Z0-9OoIl]{5}[0-9OoIl]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b',
    re.IGNORECASE
)
GSTIN_WITH_LABEL = re.compile(
    r'(?:gstin|gst\s*(?:no|number|in))[\s:—\-]+([0-9A-Z\s]{13,15})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# TAN (Tax Deduction Account Number)
# Format: AAAA99999A (4 alpha + 5 digits + 1 alpha)
# ─────────────────────────────────────────────

TAN_STRICT = re.compile(r'\b([A-Z]{4}[0-9]{5}[A-Z])\b')
TAN_WITH_LABEL = re.compile(
    r'(?:tan|tax\s*deduction\s*account)[\s:—\-]+([A-Z0-9]{10})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# CIN (Company Identification Number)
# Format: L/U + 5 digits + 2 alpha + 4 digits + PTC/PLC/... + 6 digits
# ─────────────────────────────────────────────

CIN_STRICT = re.compile(
    r'\b([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b'
)
CIN_WITH_LABEL = re.compile(
    r'(?:cin|company\s*identification)[\s:—\-]+([A-Z0-9]{21})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# ASSESSMENT YEAR (AY) / FINANCIAL YEAR (FY)
# ─────────────────────────────────────────────

AY_PATTERN = re.compile(
    r'(?:assessment\s*year|ay)[\s:—\-]*(\d{4}[\-\/]\d{2,4})',
    re.IGNORECASE
)
AY_STANDALONE = re.compile(
    r'\b(20\d{2}[\-\/](?:20)?\d{2})\b'
)
FY_PATTERN = re.compile(
    r'(?:financial\s*year|fy|f\.y\.)[\s:—\-]*(\d{4}[\-\/]\d{2,4})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# BANK ACCOUNT NUMBER
# Indian bank accounts: 9–18 digits
# ─────────────────────────────────────────────

ACCOUNT_NUMBER_WITH_LABEL = re.compile(
    r'(?:account\s*(?:no\.?|number))[\s:—\-]+(\d[\d\s]{8,17}\d)',
    re.IGNORECASE
)
# Standalone long digit sequence (risky without label)
ACCOUNT_NUMBER_STANDALONE = re.compile(r'\b(\d{9,18})\b')

# ─────────────────────────────────────────────
# IFSC CODE
# Format: 4 alpha + 0 + 6 alphanumeric
# ─────────────────────────────────────────────

IFSC_STRICT = re.compile(r'\b([A-Z]{4}0[A-Z0-9]{6})\b')
IFSC_WITH_LABEL = re.compile(
    r'(?:ifsc|ifsc\s*code)[\s:—\-]+([A-Z0-9]{11})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# INVOICE NUMBER
# ─────────────────────────────────────────────

INVOICE_NUMBER = re.compile(
    r'(?:invoice\s*(?:no\.?|number|#))[\s:—\-]+([A-Z0-9\-\/]{3,20})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# PHONE NUMBERS (Indian)
# ─────────────────────────────────────────────

PHONE_INDIA = re.compile(
    r'(?:(?:\+91|0091|91)?[\s\-]?)?([6-9]\d{9})\b'
)
PHONE_WITH_LABEL = re.compile(
    r'(?:mobile|phone|contact|tel)[\s:—\-]+(\+?[\d\s\-]{10,13})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────

EMAIL_PATTERN = re.compile(
    r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b'
)

# ─────────────────────────────────────────────
# DATES (Indian formats)
# ─────────────────────────────────────────────

DATE_DDMMYYYY = re.compile(
    r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{4})\b'
)
DATE_DDMONTHYYYY = re.compile(
    r'\b(\d{1,2}[\s\-]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[\s\-]+\d{4})\b',
    re.IGNORECASE
)
DATE_YYYYMMDD = re.compile(r'\b(\d{4}[\-\/]\d{2}[\-\/]\d{2})\b')

# ─────────────────────────────────────────────
# ITR-SPECIFIC
# ─────────────────────────────────────────────

ITR_TYPE_PATTERN = re.compile(
    r'\b(ITR[\s\-]?[0-9A-Z]{1,2})\b',
    re.IGNORECASE
)
ACKNOWLEDGEMENT_NUMBER = re.compile(
    r'(?:acknowledgement\s*(?:no\.?|number)?)[\s:—\-]*(\d{12,15})',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def extract_first(pattern: re.Pattern, text: str) -> Optional[str]:
    """Return first match group (group 1) or None."""
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    return None


def extract_all(pattern: re.Pattern, text: str) -> list[str]:
    """Return all non-overlapping matches of group 1."""
    return [m.group(1).strip() for m in pattern.finditer(text)]


def is_valid_pan(pan: str) -> bool:
    """Validate PAN: 5 alpha, 4 digits, 1 alpha."""
    return bool(re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', pan.upper()))


def is_valid_gstin(gstin: str) -> bool:
    """Basic GSTIN structural validation."""
    gstin = gstin.upper().replace(" ", "")
    return bool(re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]', gstin))


def is_valid_aadhaar(aadhaar: str) -> bool:
    """Validate Aadhaar: exactly 12 digits."""
    digits_only = re.sub(r'\D', '', aadhaar)
    return len(digits_only) == 12 and digits_only[0] != '0'


def is_valid_ifsc(ifsc: str) -> bool:
    """Validate IFSC: 4 alpha + 0 + 6 alphanumeric."""
    return bool(re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc.upper()))


def normalize_aadhaar(raw: str) -> str:
    """Normalize Aadhaar to XXXX XXXX XXXX format."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 12:
        return f"{digits[:4]} {digits[4:8]} {digits[8:]}"
    return raw
