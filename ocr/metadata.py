"""
DocuFlow AI - Metadata Extraction Engine  (v2 — Production Hardened)

Extracts structured metadata from OCR text.

v2 Changes:
- Aadhaar extraction: aggressive false-positive prevention.
  Plain 12-digit sequences (acknowledgement numbers, account numbers,
  transaction IDs, invoice IDs) are REJECTED unless strong positive
  evidence exists (Aadhaar keyword + formatted 4-4-4 pattern OR
  label-anchored match).
- PAN extraction: tolerant fallback now validates the corrected form
  only — not the raw OCR text.
- GSTIN extraction: enforces embedded PAN structure validation.
- Assessment year: rejects years outside plausible Indian IT range.
- All extractors return {"value": None, "confidence": 0} on any doubt.
"""

import re
import logging
from typing import Optional
from ocr.classifiers import (
    is_valid_extracted_name
)
from ocr.constants import NAME_LABELS, NAME_BLACKLIST
from ocr.regex_patterns import (
    PAN_STRICT,
    PAN_TOLERANT,
    PAN_WITH_LABEL,
    AADHAAR_FORMATTED,
    AADHAAR_PLAIN,
    AADHAAR_WITH_LABEL,
    AADHAAR_MASKED,
    GSTIN_STRICT,
    GSTIN_TOLERANT,
    GSTIN_WITH_LABEL,
    TAN_STRICT,
    TAN_WITH_LABEL,
    CIN_STRICT,
    AY_PATTERN,
    AY_STANDALONE,
    FY_PATTERN,
    ACCOUNT_NUMBER_WITH_LABEL,
    IFSC_STRICT,
    IFSC_WITH_LABEL,
    INVOICE_NUMBER,
    PHONE_INDIA,
    PHONE_WITH_LABEL,
    EMAIL_PATTERN,
    DATE_DDMMYYYY,
    DATE_DDMONTHYYYY,
    ITR_TYPE_PATTERN,
    ACKNOWLEDGEMENT_NUMBER,
    is_valid_pan,
    is_valid_gstin,
    is_valid_aadhaar,
    is_valid_ifsc,
    normalize_aadhaar,
    extract_first,
    extract_all,
)
from ocr.scoring import compute_field_confidence
from ocr.utils import (
    extract_lines,
    normalize_name,
    is_likely_name,
    normalize_whitespace,
)

logger = logging.getLogger(__name__)

MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
)

MONTH_PATTERN = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
GST_PERIOD_LABEL_PATTERN = re.compile(
    rf"(?:tax\s*period|return\s*period|period|month)\s*[:\-]?\s*"
    rf"({MONTH_PATTERN}\s+20\d{{2}}|\d{{1,2}}[\-/]20\d{{2}})",
    re.IGNORECASE,
)
GST_FILING_DATE_PATTERN = re.compile(
    r"(?:date\s*of\s*filing|filing\s*date|filed\s*on|arn\s*date)\s*[:\-]?\s*"
    r"(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|"
    r"\d{1,2}[\-/\s]+"
    rf"{MONTH_PATTERN}"
    r"[\-/\s]+20\d{2})",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────
# AADHAAR CONTEXT GATING — shared constants
# ─────────────────────────────────────────────

# Keywords that strongly suggest an Aadhaar document
_AADHAAR_STRONG_KW = ("aadhaar", "uidai", "enrolment", "your aadhaar")

# Patterns that indicate a number is NOT an Aadhaar (false-positive blockers)
# These appear within ≤ 120 chars of a 12-digit number on an ITR/bank doc
_NOT_AADHAAR_CONTEXT = re.compile(
    r'\b(?:'
    r'acknowledgement|ack\.?\s*no|ack\s*number'
    r'|e-?filing|efiling'
    r'|transaction|txn'
    r'|invoice\s*(?:no|number|#)'
    r'|receipt\s*(?:no|number)'
    r'|account\s*(?:no|number)'
    r'|reference\s*(?:no|number|id)'
    r'|challan\s*(?:no|number)'
    r'|serial\s*(?:no|number)'
    r'|folio'
    r')\b',
    re.IGNORECASE,
)

# Plausible Aadhaar state prefix range: 10–99 (never starts with 0)
# Aadhaar verhoeff checksum is complex; we do a lightweight sanity check.
def _aadhaar_plausible(digits: str) -> bool:
    """
    Lightweight plausibility check for a 12-digit Aadhaar candidate.
    - Must not start with 0 or 1 (UIDAI allocates from 2xxx onward)
    - Must have some digit variety (not all same digit)
    - Must pass is_valid_aadhaar()
    """
    if not is_valid_aadhaar(digits):
        return False
    if digits[0] in ('0', '1'):
        return False
    # Reject trivial sequences: all same digit, or sequential
    if len(set(digits)) < 4:
        return False
    return True


def _nearby_text(text: str, match_start: int, match_end: int, radius: int = 120) -> str:
    """Return text within `radius` chars on either side of a match."""
    return text[max(0, match_start - radius): min(len(text), match_end + radius)]


# ─────────────────────────────────────────────
# PAN EXTRACTION
# ─────────────────────────────────────────────

def extract_pan(text: str, ocr_score: float = 0.0) -> dict:
    """
    Extract PAN number from text.

    Priority:
    1. Label-anchored (PAN: ABCDE1234F)  — highest confidence
    2. Strict regex on uppercased text   — high confidence
    3. Tolerant regex (after corrections applied) — medium confidence

    False-positive guard: every candidate must pass is_valid_pan() which
    enforces the exact [A-Z]{5}[0-9]{4}[A-Z] format.
    """
    text_upper = text.upper()

    # 1. Label-anchored
    label_match = PAN_WITH_LABEL.search(text)
    if label_match:
        candidate = re.sub(r'\W', '', label_match.group(1).upper())[:10]
        if is_valid_pan(candidate):
            return {
                "value": candidate,
                "confidence": compute_field_confidence(
                    candidate,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 2. Strict pattern
    strict_match = PAN_STRICT.search(text_upper)
    if strict_match:
        pan = strict_match.group(1)
        if is_valid_pan(pan):
            return {
                "value": pan,
                "confidence": compute_field_confidence(
                    pan,
                    is_regex_match=True,
                    is_label_anchored=False,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 3. Tolerant pattern — only accept if result is a valid PAN after correction
    for m in PAN_TOLERANT.finditer(text_upper):
        candidate = m.group(1).upper()
        # Must already be fully valid (corrections.py should have fixed it)
        if re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', candidate):
            return {
                "value": candidate,
                "confidence": compute_field_confidence(
                    candidate,
                    is_regex_match=True,
                    is_label_anchored=False,
                    is_valid_format=True,
                    is_corrected=True,
                    ocr_score=ocr_score,
                ),
            }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# AADHAAR EXTRACTION  (hardened v2)
# ─────────────────────────────────────────────

def extract_aadhaar(text: str, ocr_score: float = 0.0) -> dict:
    """
    Extract Aadhaar number with strict false-positive prevention.

    Accept ONLY when:
    (a) Label-anchored (aadhaar/uid label + number), OR
    (b) Masked Aadhaar (XXXX XXXX 1234 format), OR
    (c) Formatted 4-4-4 grouping AND strong Aadhaar keyword present AND
        the nearby text does NOT indicate a different ID type.

    NEVER accept:
    - Plain 12-digit sequences without strong context.
    - Any 12-digit number near acknowledgement/transaction/account/invoice labels.
    - Numbers starting with 0 or 1 (not allocated by UIDAI).
    - Numbers with fewer than 4 unique digits.
    """
    text_lower = text.lower()
    has_strong_context = any(kw in text_lower for kw in _AADHAAR_STRONG_KW)

    # ── 1. Label-anchored (highest confidence) ──
    label_match = AADHAAR_WITH_LABEL.search(text)
    if label_match:
        raw = label_match.group(1)
        digits = re.sub(r'\D', '', raw)
        if len(digits) == 12 and _aadhaar_plausible(digits):
            normalized = normalize_aadhaar(digits)
            return {
                "value": normalized,
                "confidence": compute_field_confidence(
                    normalized,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # ── 2. Masked Aadhaar ──
    masked = AADHAAR_MASKED.search(text)
    if masked:
        return {
            "value": f"XXXX XXXX {masked.group(1)}",
            "confidence": 60,
        }

    # ── 3. Formatted 4-4-4 with strong context ──
    if has_strong_context:
        for m in AADHAAR_FORMATTED.finditer(text):
            raw = m.group(1)
            digits = re.sub(r'\D', '', raw)
            if len(digits) != 12 or not _aadhaar_plausible(digits):
                continue
            # Check nearby context for disqualifying patterns
            nearby = _nearby_text(text, m.start(), m.end(), radius=120)
            if _NOT_AADHAAR_CONTEXT.search(nearby):
                logger.debug(
                    f"Aadhaar candidate '{raw}' rejected: disqualifying context near match"
                )
                continue
            normalized = normalize_aadhaar(digits)
            return {
                "value": normalized,
                "confidence": compute_field_confidence(
                    digits,
                    is_regex_match=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # ── 4. Plain 12-digit — ONLY with strong context AND formatted pattern not found ──
    #       This is the highest-risk path; apply maximally strict gating.
    if has_strong_context:
        for m in AADHAAR_PLAIN.finditer(text):
            digits = m.group(1)
            if not _aadhaar_plausible(digits):
                continue
            nearby = _nearby_text(text, m.start(), m.end(), radius=80)
            # Require an Aadhaar keyword within the nearby window (not just anywhere in doc)
            nearby_lower = nearby.lower()
            if not any(kw in nearby_lower for kw in _AADHAAR_STRONG_KW):
                continue
            if _NOT_AADHAAR_CONTEXT.search(nearby):
                logger.debug(
                    f"Plain Aadhaar candidate '{digits}' rejected: disqualifying context"
                )
                continue
            normalized = normalize_aadhaar(digits)
            return {
                "value": normalized,
                "confidence": compute_field_confidence(
                    digits,
                    is_regex_match=True,
                    is_valid_format=True,
                    is_corrected=True,
                    ocr_score=ocr_score,
                ),
            }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# GSTIN EXTRACTION  (hardened v2)
# ─────────────────────────────────────────────

def extract_gstin(text: str, ocr_score: float = 0.0) -> dict:
    """
    Extract GSTIN with embedded PAN structure validation.

    Extra check: positions 2-11 of GSTIN must form a valid PAN structure
    (5 alpha + 4 digits + 1 alpha) after state code.
    """
    text_upper = text.upper()

    def _gstin_has_valid_pan_core(gstin: str) -> bool:
        """Verify that characters 2-11 of GSTIN follow PAN structure."""
        if len(gstin) < 12:
            return False
        pan_core = gstin[2:12]
        return bool(re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', pan_core))

    # 1. Label-anchored
    label_match = GSTIN_WITH_LABEL.search(text)
    if label_match:
        raw = label_match.group(1).strip().upper().replace(" ", "")
        if is_valid_gstin(raw) and _gstin_has_valid_pan_core(raw):
            return {
                "value": raw,
                "confidence": compute_field_confidence(
                    raw,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 2. Strict pattern with PAN core check
    strict_match = GSTIN_STRICT.search(text_upper)
    if strict_match:
        gstin = strict_match.group(1)
        if is_valid_gstin(gstin) and _gstin_has_valid_pan_core(gstin):
            return {
                "value": gstin,
                "confidence": compute_field_confidence(
                    gstin,
                    is_regex_match=True,
                    is_label_anchored=False,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 3. Tolerant pattern (only in GST context)
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("gstin", "gst", "goods and services")):
        for m in GSTIN_TOLERANT.finditer(text_upper):
            candidate = m.group(1).upper().replace(" ", "")
            if is_valid_gstin(candidate) and _gstin_has_valid_pan_core(candidate):
                return {
                    "value": candidate,
                    "confidence": compute_field_confidence(
                        candidate,
                        is_regex_match=True,
                        is_valid_format=True,
                        is_corrected=True,
                        ocr_score=ocr_score,
                    ),
                }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# TAN EXTRACTION
# ─────────────────────────────────────────────

def extract_tan(text: str, ocr_score: float = 0.0) -> dict:
    """Extract TAN (Tax Deduction Account Number) — 4 alpha + 5 digits + 1 alpha."""
    text_upper = text.upper()

    # 1. Label-anchored
    label_match = TAN_WITH_LABEL.search(text)
    if label_match:
        candidate = label_match.group(1).upper().replace(" ", "")
        if re.fullmatch(r'[A-Z]{4}[0-9]{5}[A-Z]', candidate):
            return {
                "value": candidate,
                "confidence": compute_field_confidence(
                    candidate,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 2. Strict — only extract if "tan" or "deductor" keyword nearby
    text_lower = text.lower()
    if "tan" in text_lower or "deductor" in text_lower or "form 16" in text_lower:
        m = TAN_STRICT.search(text_upper)
        if m:
            tan = m.group(1)
            # Reject if it also matches PAN format (PAN could be mistaken for TAN prefix)
            if not re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', tan):
                return {
                    "value": tan,
                    "confidence": compute_field_confidence(
                        tan,
                        is_regex_match=True,
                        is_valid_format=True,
                        ocr_score=ocr_score,
                    ),
                }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# IFSC EXTRACTION
# ─────────────────────────────────────────────

def extract_ifsc(text: str, ocr_score: float = 0.0) -> dict:
    """Extract IFSC code with structural validation."""
    # 1. Label-anchored
    label_match = IFSC_WITH_LABEL.search(text)
    if label_match:
        candidate = label_match.group(1).upper().replace(" ", "")
        if is_valid_ifsc(candidate):
            return {
                "value": candidate,
                "confidence": compute_field_confidence(
                    candidate,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 2. Strict — only in bank context
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("ifsc", "bank", "branch", "account")):
        m = IFSC_STRICT.search(text.upper())
        if m:
            ifsc = m.group(1)
            if is_valid_ifsc(ifsc):
                return {
                    "value": ifsc,
                    "confidence": compute_field_confidence(
                        ifsc,
                        is_regex_match=True,
                        is_valid_format=True,
                        ocr_score=ocr_score,
                    ),
                }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# ASSESSMENT YEAR EXTRACTION
# ─────────────────────────────────────────────

# Plausible Indian IT AY range: 2000-01 to 2035-36
_AY_MIN_YEAR = 2000
_AY_MAX_YEAR = 2035


def _validate_ay(ay_str: str) -> bool:
    """Validate that an AY string represents a plausible Indian financial year."""
    try:
        parts = re.split(r'[\-\/]', ay_str)
        start_year = int(parts[0])
        if start_year < _AY_MIN_YEAR or start_year > _AY_MAX_YEAR:
            return False
        if len(parts) > 1:
            end_suffix = int(parts[1])
            # end_suffix is either 2-digit (21) or 4-digit (2021)
            expected_end = (start_year + 1) % 100 if end_suffix < 100 else start_year + 1
            if end_suffix != expected_end:
                return False
        return True
    except (ValueError, IndexError):
        return False


def extract_assessment_year(text: str, ocr_score: float = 0.0) -> dict:
    """
    Extract Assessment Year or Financial Year.

    Priority: AY label > FY label > standalone year pattern.
    Validates plausibility before returning.
    """
    # 1. Assessment Year label
    m = AY_PATTERN.search(text)
    if m:
        ay = m.group(1).strip()
        if _validate_ay(ay):
            return {
                "value": ay,
                "confidence": compute_field_confidence(
                    ay,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 2. Financial Year label
    m = FY_PATTERN.search(text)
    if m:
        fy = m.group(1).strip()
        if _validate_ay(fy):
            return {
                "value": fy,
                "confidence": compute_field_confidence(
                    fy,
                    is_regex_match=True,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                ),
            }

    # 3. Standalone year pattern — only in documents with AY/tax context
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("assessment", "financial year", "income tax", "itr", "ay")):
        for m in AY_STANDALONE.finditer(text):
            ay = m.group(1).strip()
            if _validate_ay(ay):
                return {
                    "value": ay,
                    "confidence": compute_field_confidence(
                        ay,
                        is_regex_match=True,
                        is_valid_format=True,
                        ocr_score=ocr_score,
                    ),
                }

    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# NAME DETECTION
# ─────────────────────────────────────────────

def _clean_name_candidate(candidate: str) -> str:
    """
    Clean a name candidate:
    - Strip leading/trailing garbage
    - Remove numeric suffixes (names don't contain digits)
    - Remove common title prefixes OCR includes
    - Remove leading preposition phrases that indicate a label fragment
      (e.g. "Of Premises" → rejected; "And Address" → rejected)
    - Limit to 60 chars
    """
    if not candidate:
        return ""
    candidate = re.sub(r'^[\W_]+|[\W_]+$', '', candidate)
    candidate = re.sub(r'\d.*', '', candidate).strip()
    candidate = re.sub(
        r'^(name|assessee|applicant|mr\.?|mrs\.?|ms\.?|dr\.?)\s*',
        '', candidate, flags=re.IGNORECASE
    )
    candidate = candidate.strip(' :|-')
    # Strip if it starts with a preposition (catches "Of Premises", "And Address", etc.)
    candidate = re.sub(
        r'^(of|and|the|in|to|for|from|by|with|on|at|as|an|a|see|per)\s+',
        '', candidate, flags=re.IGNORECASE
    ).strip()
    return candidate[:60].strip()


def extract_name(text: str, pan_value: Optional[str] = None, ocr_score: float = 0.0) -> dict:
    """
    Detect the primary person/entity name from document text.

    Strategy order (by confidence):
    1. Label-anchored patterns (e.g., "Name: Jayant Jain")
    2. PAN-proximate name (name near PAN in the text)
    3. Top-of-document heuristic (name often in first ~10 lines)
    """
    lines = extract_lines(text)
    if not lines:
        return {"value": None, "confidence": 0}

    candidates: list[tuple[str, int, str]] = []

    # ── Strategy 1: Label-anchored ──
    # IMPORTANT: the capture group is intentionally limited to same-line content.
    # ITR docs layout labels like:
    #   "Name and Address of Premises   SOME VALUE"
    # The regex must NOT capture "Of Premises" when the label is just "name".
    # We enforce this by:
    #   a) Splitting on the first newline (already done via .split('\n')[0])
    #   b) Using a tighter label-match: only fire when the label appears as a
    #      standalone word or with a colon/dash separator — not mid-phrase.
    for label in NAME_LABELS:
        # Require label at word boundary, followed by optional separator,
        # then the value.  The \b before and after prevents "name" matching
        # inside "name and address of premises".
        pattern = re.compile(
            r'(?<![A-Za-z])(?:' + re.escape(label) + r')(?![A-Za-z])'
            r'\s*[:\-\|]?\s*([A-Za-z][A-Za-z\s\.\-]{2,50})',
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            candidate = m.group(1).strip().split('\n')[0].strip()
            candidate = _clean_name_candidate(candidate)
            if (candidate
                and is_likely_name(candidate, NAME_BLACKLIST)
                and is_valid_extracted_name(candidate)):
                confidence = compute_field_confidence(
                    candidate,
                    is_label_anchored=True,
                    is_valid_format=True,
                    ocr_score=ocr_score,
                )
                candidates.append((candidate, confidence, "label"))
                logger.debug(f"Name candidate (label): '{candidate}' conf={confidence}")

    # ── Strategy 2: PAN-proximate name ──
    if pan_value:
        pan_idx = text.upper().find(pan_value)
        if pan_idx >= 0:
            window = text[max(0, pan_idx - 300): pan_idx + len(pan_value) + 200]
            for label in ["name", "assessee", "applicant"]:
                lpattern = re.compile(
                    r'(?:' + label + r')\s*[:\-\|]?\s*([A-Za-z][A-Za-z\s\.\-]{2,50})',
                    re.IGNORECASE,
                )
                for m in lpattern.finditer(window):
                    candidate = m.group(1).strip().split('\n')[0].strip()
                    candidate = _clean_name_candidate(candidate)
                    if (candidate 
                and is_likely_name(candidate, NAME_BLACKLIST)
                and is_valid_extracted_name(candidate)):
                        confidence = compute_field_confidence(
                            candidate,
                            is_label_anchored=True,
                            is_valid_format=True,
                            ocr_score=ocr_score,
                        )
                        candidates.append((candidate, confidence + 10, "pan_proximate"))

    # ── Strategy 3: Top-of-document heuristic (only if no label match found) ──
    if not candidates:
        for line in lines[:12]:
            if len(line) < 4 or len(line) > 60:
                continue
            if re.fullmatch(r'[\d\W]+', line):
                continue
            # Skip lines that contain document structure keywords
            if any(kw in line.lower() for kw in [
                "income tax", "government", "india", "department",
                "permanent account", "central", "processing", "centre",
                "aadhaar", "uidai", "gst", "invoice", "certificate",
                "acknowledgement", "return", "salary", "form",
                "premises", "address", "place of", "registered",
                "principal", "verification", "e-filing", "efiling",
                "see rule", "rule 12", "assessment year",
                "account summary", "account statement", "statement summary",
                "transaction summary", "account details", "customer id",
            ]):
                continue
            # Skip lines that start with a preposition — always label fragments
            first_word = line.split()[0].lower().rstrip('.,:-') if line.split() else ""
            if first_word in {"of", "and", "the", "in", "to", "for", "from",
                              "by", "with", "on", "at", "as", "an", "a", "see"}:
                continue
            alpha_ratio = sum(1 for c in line if c.isalpha()) / max(len(line), 1)
            if alpha_ratio >= 0.7:
                candidate = _clean_name_candidate(line)
                # Top-heuristic requires at least 2 words (first + last name)
                # to reduce single-word label false positives
                if (candidate
                    and len(candidate.split()) >= 2
                    and is_likely_name(candidate, NAME_BLACKLIST)
                    and is_valid_extracted_name(candidate)):
                    candidates.append((candidate, 40, "top_heuristic"))

    if not candidates:
        return {"value": None, "confidence": 0}

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_name, best_conf, best_strategy = candidates[0]
    print("BEST NAME:", best_name)
    print("VALID:", is_valid_extracted_name(best_name))
    best_name = normalize_name(best_name)
    if not is_valid_extracted_name(best_name):
        logger.info(
        f"Rejected invalid final name: '{best_name}'"

    )   
        print("REJECTED NAME:", best_name)

        return {
        "value": None,
        "confidence": 0
    }
    logger.info(f"Name detected: '{best_name}' (strategy={best_strategy}, conf={best_conf})")
    print("FINAL NAME CHECK:", best_name)
    print("VALID?", is_valid_extracted_name(best_name))
    return {"value": best_name if best_name else None, "confidence": best_conf}


# ─────────────────────────────────────────────
# SUPPLEMENTAL FIELD EXTRACTORS
# ─────────────────────────────────────────────

def extract_invoice_number(text: str, ocr_score: float = 0.0) -> dict:
    match = INVOICE_NUMBER.search(text)
    if match:
        val = match.group(1).strip()
        return {
            "value": val,
            "confidence": compute_field_confidence(
                val,
                is_regex_match=True,
                is_label_anchored=True,
                is_valid_format=True,
                ocr_score=ocr_score,
            ),
        }
    return {"value": None, "confidence": 0}


def extract_phone(text: str, ocr_score: float = 0.0) -> dict:
    label_match = PHONE_WITH_LABEL.search(text)
    if label_match:
        digits = re.sub(r'\D', '', label_match.group(1))[-10:]
        if len(digits) == 10 and digits[0] in "6789":
            return {"value": digits, "confidence": 75}
    plain = PHONE_INDIA.search(text)
    if plain:
        return {"value": plain.group(1), "confidence": 55}
    return {"value": None, "confidence": 0}


def extract_email(text: str) -> dict:
    match = EMAIL_PATTERN.search(text)
    if match:
        return {"value": match.group(1).lower(), "confidence": 90}
    return {"value": None, "confidence": 0}


def extract_dates(text: str) -> list[str]:
    """Return all date strings found in text, deduplicated."""
    dates = []
    for pattern in [DATE_DDMONTHYYYY, DATE_DDMMYYYY]:
        dates.extend(m.group(1) for m in pattern.finditer(text))
    return list(dict.fromkeys(dates))


def extract_gst_period(text: str) -> dict:
    text_lower = (text or "").lower()
    if not any(keyword in text_lower for keyword in ("gst", "gstin", "gstr", "goods and services")):
        return {
            "month": None,
            "filing_date": None,
            "confidence": 0,
        }

    period_match = GST_PERIOD_LABEL_PATTERN.search(text)
    date_match = GST_FILING_DATE_PATTERN.search(text)

    return {
        "month": period_match.group(1).strip() if period_match else None,
        "filing_date": date_match.group(1).strip() if date_match else None,
        "confidence": 85 if period_match or date_match else 0,
    }


def extract_itr_type(text: str) -> dict:
    match = ITR_TYPE_PATTERN.search(text)
    if match:
        itr = match.group(1).upper().replace(" ", "-").replace("--", "-")
        return {"value": itr, "confidence": 85}
    return {"value": None, "confidence": 0}


def extract_acknowledgement_number(text: str) -> dict:
    """
    Extract ITR acknowledgement number.

    IMPORTANT: This must be label-anchored only.
    A plain 12-15 digit sequence without the "acknowledgement" label must
    NOT be returned — it would false-positive as Aadhaar upstream.
    """
    match = ACKNOWLEDGEMENT_NUMBER.search(text)
    if match:
        val = match.group(1).strip()
        # Additional sanity: acknowledgement numbers are 12-15 digits and purely numeric
        if re.fullmatch(r'\d{12,15}', val):
            return {"value": val, "confidence": 85}
    return {"value": None, "confidence": 0}


# ─────────────────────────────────────────────
# MASTER METADATA EXTRACTOR
# ─────────────────────────────────────────────

def extract_all_metadata(text: str, ocr_score: float = 0.0) -> dict:
    """
    Run all extractors on corrected OCR text.

    Returns a comprehensive metadata dict with confidence scores for every field.
    All extractors prioritise precision over recall.
    """
    pan = extract_pan(text, ocr_score)
    pan_value = pan.get("value")

    aadhaar = extract_aadhaar(text, ocr_score)
    gstin = extract_gstin(text, ocr_score)
    tan = extract_tan(text, ocr_score)
    ay = extract_assessment_year(text, ocr_score)
    ifsc = extract_ifsc(text, ocr_score)
    name = extract_name(text, pan_value=pan_value, ocr_score=ocr_score)
    itr_type = extract_itr_type(text)
    ack_num = extract_acknowledgement_number(text)
    invoice_num = extract_invoice_number(text, ocr_score)
    phone = extract_phone(text, ocr_score)
    email = extract_email(text)
    dates = extract_dates(text)
    gst_period = extract_gst_period(text)

    logger.info(
        f"Metadata: PAN={pan.get('value')} Aadhaar={aadhaar.get('value')} "
        f"GSTIN={gstin.get('value')} TAN={tan.get('value')} "
        f"AY={ay.get('value')} Name={name.get('value')}"
    )

    return {
        "detected_name": name,
        "year": ay,
        "important_ids": {
            "pan": pan,
            "aadhaar": aadhaar,
            "gstin": gstin,
            "tan": tan,
            "ifsc": ifsc,
        },
        "supplemental": {
            "itr_type": itr_type,
            "acknowledgement_number": ack_num,
            "invoice_number": invoice_num,
            "phone": phone,
            "email": email,
            "dates": dates,
            "gst_period": gst_period,
        },
    }
