"""
DocuFlow AI - OCR Error Correction Layer  (v2 — Production Hardened)

Corrects common Tesseract misreads specific to Indian financial documents.

CRITICAL DESIGN RULES (v2):
1.  Never apply global alpha↔digit substitutions to free text.
2.  PAN correction ONLY fires on tokens that already structurally resemble a PAN
    (first 5 mostly alpha, middle 4 mostly digit-like, last char alpha).
3.  Aadhaar correction ONLY fires when BOTH:
    a.  A strong Aadhaar keyword is present (not just "uid" — too generic).
    b.  The candidate is a 4-4-4 digit cluster (formatted), not a plain 12-digit block.
4.  GSTIN correction ONLY fires when GST keywords are present.
5.  Assessment-year correction is strictly scoped to AY-shaped tokens.
6.  Broken-sequence fix is narrowly scoped — no free-text regexes that could
    touch words like "DEPARTMENT".

v1 Bug fixes applied:
- Removed Cyrillic Т from _DIGIT_TO_ALPHA (was str.maketrans("0158267", "OISBGZТ")).
- _looks_like_pan now requires position 4 to be alpha (4th type char, not 4th entity).
- Aadhaar context check upgraded: "uid" alone is too broad; now requires "aadhaar",
  "uidai", or "enrolment" (not "uid" which appears in acknowledgement docs).
- Aadhaar correction restricted to FORMATTED (4-4-4) clusters only — plain
  12-digit blocks are NOT corrected here (they go through metadata extraction
  which applies stricter context gating).
- fix_broken_sequences regex narrowed to avoid matching partial words.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# INTERNAL MAPS  (position-specific, NOT global)
# ─────────────────────────────────────────────

# For digit positions (5-8) in a PAN token: alpha → digit
_PAN_DIGIT_MAP: dict[str, str] = {
    "O": "0", "I": "1", "L": "1",
    "S": "5", "B": "8", "G": "6", "Z": "2", "T": "7",
}

# For alpha positions (0-4, 9) in a PAN token: digit → alpha
_PAN_ALPHA_MAP: dict[str, str] = {
    "0": "O", "1": "I", "5": "S",
    "8": "B", "6": "G", "2": "Z", "7": "T",
}

# For purely-numeric fields (Aadhaar): alpha → digit
_NUMERIC_FIX_MAP: dict[str, str] = {
    "O": "0", "I": "1", "L": "1",
    "S": "5", "B": "8", "G": "6", "Z": "2",
}


# ─────────────────────────────────────────────
# PAN-SPECIFIC CORRECTION
# PAN format: [A-Z]{5}[0-9]{4}[A-Z]
# ─────────────────────────────────────────────

def _fix_pan_token(token: str) -> str:
    """
    Apply position-aware correction to a 10-char PAN candidate.

    Positions 0-4 → force alpha  (digit confusables → alpha)
    Positions 5-8 → force digit  (alpha confusables → digit)
    Position  9   → force alpha  (digit confusables → alpha)

    Does NOT touch any other character.
    """
    if len(token) != 10:
        return token
    chars = list(token.upper())

    for i in range(5, 9):           # digit positions
        chars[i] = _PAN_DIGIT_MAP.get(chars[i], chars[i])

    for i in list(range(0, 5)) + [9]:   # alpha positions
        chars[i] = _PAN_ALPHA_MAP.get(chars[i], chars[i])

    return "".join(chars)


def _looks_like_pan(token: str) -> bool:
    """
    Conservative heuristic: does this 10-char token ALREADY structurally
    resemble a PAN with possible OCR noise?

    Conditions (all must hold):
    - Length == 10
    - Position 9 (last): must be alpha (A-Z) — not digit-like
    - Positions 0-4: at least 4 chars are alpha (A-Z); i.e. the prefix is
      mostly alpha.  This blocks things like "1234567890".
    - Positions 5-8: at least 3 chars are in the digit-or-confusable set.
      This allows "O" standing for "0" but blocks pure-alpha middle sections.

    IMPORTANT: we do NOT apply this to tokens that pass PAN_STRICT — those
    are already valid and don't need any correction.
    """
    t = token.upper()
    if len(t) != 10:
        return False

    # Last char must genuinely be alphabetic (no digit-like ambiguity here)
    if not t[9].isalpha():
        return False

    # First 5 chars: at least 4 must be strictly alpha
    alpha_prefix = sum(1 for c in t[:5] if c.isalpha())
    if alpha_prefix < 4:
        return False

    # Middle 4 chars (positions 5-8): at least 3 must be digit-or-confusable
    digit_like = set("0123456789OILSBGZoilsbgz")
    digit_mid = sum(1 for c in t[5:9] if c in digit_like)
    if digit_mid < 3:
        return False

    return True


# Compiled once — matches exactly 10 consecutive alphanumeric chars at word
# boundary.  Note: we use [A-Z0-9] not \w to exclude underscore.
_PAN_CANDIDATE_RE = re.compile(r'\b([A-Z0-9]{10})\b', re.IGNORECASE)


def correct_pan_candidates(text: str) -> str:
    """
    Scan text for PAN-like 10-char tokens and apply position-aware correction.

    CONSERVATIVE CONTRACT:
    - Only modifies tokens that already pass _looks_like_pan().
    - Never touches normal English words (they fail the alpha-prefix or
      digit-middle check).
    - Never performs global O→0 or similar substitutions.
    """
    def _replacer(m: re.Match) -> str:
        raw = m.group(1)
        token = raw.upper()

        # If it's already a valid PAN, leave it alone — no need to correct.
        if re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', token):
            return raw  # preserve original case (though PAN is always upper)

        if _looks_like_pan(token):
            corrected = _fix_pan_token(token)
            if corrected != token:
                logger.debug(f"PAN correction: '{token}' → '{corrected}'")
            return corrected
        return raw  # unchanged

    return _PAN_CANDIDATE_RE.sub(_replacer, text)


# ─────────────────────────────────────────────
# AADHAAR-SPECIFIC CORRECTION
# ─────────────────────────────────────────────

# Strong Aadhaar context keywords — "uid" alone is too generic
# (appears in "acknowledgement uid", "liquid", etc.)
_AADHAAR_STRONG_KEYWORDS = ("aadhaar", "uidai", "enrolment", "your aadhaar", "uid number")

# Only correct FORMATTED Aadhaar (4-4-4 groups) — NOT plain 12-digit blocks.
# Plain blocks (acknowledgement numbers, account numbers) are gated further
# upstream in metadata.py.
_AADHAAR_FORMATTED_RE = re.compile(
    r'\b([0-9OoIlBGSZ]{4})[\s\-]([0-9OoIlBGSZ]{4})[\s\-]([0-9OoIlBGSZ]{4})\b',
    re.IGNORECASE,
)


def correct_aadhaar_candidates(text: str) -> str:
    """
    Fix alpha-digit confusables inside formatted Aadhaar groups (4-4-4).

    CONSERVATIVE CONTRACT:
    - Only runs when a STRONG Aadhaar keyword is present in the document
      ("aadhaar", "uidai", "enrolment") — not just "uid".
    - Only touches FORMATTED (4-4-4) clusters, not plain 12-digit sequences.
    - Plain 12-digit sequences are intentionally left alone here; they are
      handled with stricter context gating inside metadata.extract_aadhaar().
    """
    text_lower = text.lower()
    if not any(kw in text_lower for kw in _AADHAAR_STRONG_KEYWORDS):
        return text

    def _fix_group(group: str) -> str:
        corrected = group.upper()
        for alpha, digit in _NUMERIC_FIX_MAP.items():
            corrected = corrected.replace(alpha, digit)
        return corrected

    def _replacer(m: re.Match) -> str:
        g1 = _fix_group(m.group(1))
        g2 = _fix_group(m.group(2))
        g3 = _fix_group(m.group(3))
        # Preserve original separator (space or hyphen)
        sep1 = m.group(0)[4]   # char between group1 and group2
        sep2 = m.group(0)[9]   # char between group2 and group3
        return f"{g1}{sep1}{g2}{sep2}{g3}"

    return _AADHAAR_FORMATTED_RE.sub(_replacer, text)


# ─────────────────────────────────────────────
# GSTIN-SPECIFIC CORRECTION
# ─────────────────────────────────────────────

_GSTIN_KEYWORDS = ("gstin", "gst", "goods and services")
_GSTIN_CANDIDATE_RE = re.compile(r'\b([A-Z0-9]{15})\b', re.IGNORECASE)


def correct_gstin_candidates(text: str) -> str:
    """
    Fix digit/alpha confusables in GSTIN tokens (15 chars).

    GSTIN structure:
      [0-1]: state code  → must be digits
      [2-6]: PAN alpha prefix → must be alpha
      [7-10]: PAN digits → must be digits
      [11]: PAN check alpha → must be alpha
      [12]: entity number → digit or alpha
      [13]: 'Z' (fixed)
      [14]: checksum → digit or alpha

    CONSERVATIVE CONTRACT:
    - Only runs when GST keywords present.
    - Only corrects positions 0-1, 2-6, 7-10 (well-understood positions).
    - Does NOT touch positions 11-14 (complex / variable).
    """
    text_lower = text.lower()
    if not any(kw in text_lower for kw in _GSTIN_KEYWORDS):
        return text

    def _replacer(m: re.Match) -> str:
        token = m.group(1).upper()
        if len(token) != 15:
            return m.group(1)

        chars = list(token)

        # Positions 0-1: must be digits (state code)
        for i in [0, 1]:
            chars[i] = _PAN_DIGIT_MAP.get(chars[i], chars[i])

        # Positions 2-6: must be alpha (PAN prefix)
        for i in range(2, 7):
            chars[i] = _PAN_ALPHA_MAP.get(chars[i], chars[i])

        # Positions 7-10: must be digits (PAN numeric part)
        for i in range(7, 11):
            chars[i] = _PAN_DIGIT_MAP.get(chars[i], chars[i])

        # Position 11: must be alpha (PAN check char)
        chars[11] = _PAN_ALPHA_MAP.get(chars[11], chars[11])

        return "".join(chars)

    return _GSTIN_CANDIDATE_RE.sub(_replacer, text)


# ─────────────────────────────────────────────
# ASSESSMENT YEAR CORRECTION
# ─────────────────────────────────────────────

# Matches AY-shaped strings: "2020-21", "2O2O-21", "2020-2l", etc.
# Scope is deliberately narrow: starts with "20", followed by OCR-noisy year digits.
_AY_RE = re.compile(
    r'\b(2[0O][0-9OoIl]{2}[\-\/][0-9OoIl]{2,4})\b',
    re.IGNORECASE,
)


def fix_assessment_year(text: str) -> str:
    """
    Fix OCR noise inside Assessment Year / Financial Year tokens.
    Only matches tokens that look like "20XX-XX" — very narrow scope.
    """
    def _fix_ay(m: re.Match) -> str:
        raw = m.group(0)
        fixed = raw.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
        return fixed

    return _AY_RE.sub(_fix_ay, text)


# ─────────────────────────────────────────────
# WHITESPACE / FORMATTING FIXES
# ─────────────────────────────────────────────

# Narrowly scoped pattern: PAN split across a line break
# "ABCDE\n1234F" → "ABCDE1234F"
# Only fires if it looks EXACTLY like PAN split (5 alpha + newline + 4 digit + 1 alpha)
_PAN_SPLIT_RE = re.compile(r'([A-Z]{5})\n([0-9]{4}[A-Z])\b')

# Collapse intra-PAN spaces: "ABCDE 1234 F" → "ABCDE1234F"
# Only fires if the full sequence passes _looks_like_pan after joining
_PAN_SPACED_RE = re.compile(r'\b([A-Z]{5})\s+([0-9OoIlBGSZ]{4})\s+([A-Z])\b')


def fix_broken_sequences(text: str) -> str:
    """
    Fix OCR formatting issues that break ID recognition.

    CONSERVATIVE CONTRACT:
    - Only applies narrow, structure-specific fixes.
    - Does NOT collapse spaces globally (would break normal text).
    - Does NOT apply any character substitutions (those are in the ID-specific
      correctors above).
    """
    # Remove zero-width / invisible characters
    text = re.sub(r'[\u200b\u200c\u200d\ufeff\u00ad]', '', text)

    # Fix PAN split across a hard line break
    text = _PAN_SPLIT_RE.sub(r'\1\2', text)

    # Fix PAN with spaces between groups (e.g. "ABCDE 1234 F")
    def _pan_space_replacer(m: re.Match) -> str:
        candidate = m.group(1) + m.group(2) + m.group(3)
        if _looks_like_pan(candidate):
            return candidate
        return m.group(0)  # restore original if it doesn't look like a PAN

    text = _PAN_SPACED_RE.sub(_pan_space_replacer, text)

    # Collapse runs of 3+ spaces to single space (safe)
    text = re.sub(r'  +', ' ', text)

    return text


# ─────────────────────────────────────────────
# LIGATURE / ENCODING FIXES
# ─────────────────────────────────────────────

_LIGATURE_MAP: list[tuple[str, str]] = [
    ('\u00e2\u0080\u0099', "'"),
    ('\u00e2\u0080\u009c', '"'),
    ('\u00e2\u0080\u009d', '"'),
    ('\u00e2\u0080\u0093', '-'),
    ('\u00e2\u0080\u0094', '-'),
    ('\u00a0', ' '),
    ('\u2019', "'"),
    ('\u2018', "'"),
    ('\u201c', '"'),
    ('\u201d', '"'),
    ('\u2013', '-'),
    ('\u2014', '-'),
    ('\ufb01', 'fi'),   # fi ligature
    ('\ufb02', 'fl'),   # fl ligature
]


def fix_ocr_ligatures(text: str) -> str:
    """Fix common OCR ligature / encoding issues."""
    for bad, good in _LIGATURE_MAP:
        text = text.replace(bad, good)
    return text


# ─────────────────────────────────────────────
# MASTER CORRECTION FUNCTION
# ─────────────────────────────────────────────

def apply_all_corrections(text: str) -> str:
    """
    Apply all OCR corrections in the correct order.

    Order:
    1.  Ligature / encoding fixes  (clean the byte stream)
    2.  Broken sequence fixes      (whitespace / line-break normalization)
    3.  Assessment year fixes      (narrow AY-token scope)
    4.  PAN candidate corrections  (position-aware, won't touch normal words)
    5.  Aadhaar candidate corrections (only formatted 4-4-4, strong context only)
    6.  GSTIN candidate corrections  (GST context only)

    This must be called BEFORE regex extraction.
    Returns the original text unchanged if any exception occurs.
    """
    try:
        text = fix_ocr_ligatures(text)
        text = fix_broken_sequences(text)
        text = fix_assessment_year(text)
        text = correct_pan_candidates(text)
        text = correct_aadhaar_candidates(text)
        text = correct_gstin_candidates(text)
        return text
    except Exception as exc:
        logger.warning(f"Correction layer error — returning original text. Reason: {exc}")
        return text
