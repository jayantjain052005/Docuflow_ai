"""
DocuFlow AI - OCR Scoring System

Scores multiple OCR outputs and selects the best one.

Scoring factors (all weighted):
1. Indian document keyword hits
2. Valid PAN / Aadhaar / GSTIN found
3. Word count (proxy for content density)
4. Alphanumeric density
5. Assessment year patterns
6. Presence of key structural patterns (labels, tables, etc.)
"""

import re
import logging
from typing import Optional

from ocr.constants import (
    OCR_SCORE_KEYWORDS,
    SCORE_PAN_MATCH,
    SCORE_AADHAAR_MATCH,
    SCORE_GSTIN_MATCH,
    SCORE_KEYWORD_HIT,
    SCORE_WORD_COUNT_FACTOR,
    SCORE_ALNUM_DENSITY_FACTOR,
    MIN_ACCEPTABLE_OCR_SCORE,
)
from ocr.regex_patterns import (
    PAN_STRICT,
    AADHAAR_FORMATTED,
    AADHAAR_PLAIN,
    GSTIN_STRICT,
    AY_PATTERN,
    AY_STANDALONE,
)

logger = logging.getLogger(__name__)


def score_ocr_text(text: str) -> float:
    """
    Score a single OCR output for quality and information density.

    Higher score = more likely to be correct OCR output.

    Returns float score (higher is better, no upper bound).
    """
    if not text or len(text.strip()) < 10:
        return 0.0

    score = 0.0
    text_lower = text.lower()

    # ── 1. Indian document keyword hits ──
    for keyword in OCR_SCORE_KEYWORDS:
        if keyword in text_lower:
            score += SCORE_KEYWORD_HIT

    # ── 2. Valid ID patterns ──
    if PAN_STRICT.search(text.upper()):
        score += SCORE_PAN_MATCH
        logger.debug("OCR score: PAN found +30")

    # Aadhaar scoring: only award points for a formatted 4-4-4 Aadhaar pattern.
    # The old check (AADHAAR_PLAIN + total digit count) falsely rewarded ITR
    # acknowledgement numbers, bank account numbers, and other 12-digit sequences.
    # We also require a strong Aadhaar keyword to avoid false positives.
    _text_lower_for_scoring = text.lower()
    _aadhaar_kw_present = any(
        kw in _text_lower_for_scoring
        for kw in ("aadhaar", "uidai", "enrolment")
    )
    _aadhaar_formatted_found = bool(AADHAAR_FORMATTED.search(text))
    if _aadhaar_formatted_found and _aadhaar_kw_present:
        score += SCORE_AADHAAR_MATCH

    if GSTIN_STRICT.search(text.upper()):
        score += SCORE_GSTIN_MATCH

    # ── 3. Assessment year presence ──
    if AY_PATTERN.search(text) or AY_STANDALONE.search(text):
        score += 15

    # ── 4. Word count (information density) ──
    words = text.split()
    score += len(words) * SCORE_WORD_COUNT_FACTOR

    # ── 5. Alphanumeric density ──
    total_chars = len(text)
    alnum_chars = sum(1 for c in text if c.isalnum())
    if total_chars > 0:
        alnum_ratio = alnum_chars / total_chars
        score += alnum_ratio * 100 * SCORE_ALNUM_DENSITY_FACTOR

    # ── 6. Structured patterns (colon-separated key-value pairs) ──
    # These suggest a properly parsed document
    kv_pairs = re.findall(r'\b\w[\w\s]{2,20}:\s*\S', text)
    score += len(kv_pairs) * 2

    # ── 7. Garbage penalties ──
    # High ratio of special chars = bad OCR
    special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace() and c not in '.,:;-/()[]\'\"')
    if total_chars > 0 and special_chars / total_chars > 0.3:
        score -= 20

    # Very short text = probably bad OCR
    if len(text.strip()) < 50:
        score -= 10

    return max(score, 0.0)


def select_best_ocr(results: list[dict]) -> dict:
    """
    Given a list of OCR result dicts, select the best one.

    Each result dict must have:
    - 'text': str — the OCR text
    - 'config': str — description of OCR config used
    - 'score': float (optional, will be computed if missing)

    Returns the best result dict with 'score' populated.
    """
    if not results:
        return {"text": "", "config": "none", "score": 0.0}

    # Score all results that don't already have a score
    for r in results:
        if "score" not in r or r["score"] is None:
            r["score"] = score_ocr_text(r.get("text", ""))

    # Select highest score
    best = max(results, key=lambda r: r["score"])

    logger.info(
        f"Best OCR: config='{best.get('config')}' score={best['score']:.1f} "
        f"text_len={len(best.get('text', ''))}"
    )

    if best["score"] < MIN_ACCEPTABLE_OCR_SCORE:
        logger.warning(f"Best OCR score {best['score']:.1f} is below minimum threshold.")

    return best


def merge_ocr_results(results: list[dict]) -> str:
    """
    Alternative to best-selection: merge all OCR outputs
    by taking the union of unique lines from high-scoring passes.

    Useful when different passes capture different parts of the document.

    Returns merged text string.
    """
    if not results:
        return ""

    # Sort by score descending
    scored = sorted(results, key=lambda r: r.get("score", 0), reverse=True)

    # Use top result as base
    base_text = scored[0].get("text", "")

    # Extract lines from all results that aren't already in base
    base_lines_lower = {line.lower().strip() for line in base_text.splitlines() if line.strip()}
    extra_lines = []

    for r in scored[1:]:
        for line in r.get("text", "").splitlines():
            line_stripped = line.strip()
            if line_stripped and line_stripped.lower() not in base_lines_lower:
                # Check if this line contains useful info (ID, keyword, etc.)
                if _line_is_informative(line_stripped):
                    extra_lines.append(line_stripped)
                    base_lines_lower.add(line_stripped.lower())

    if extra_lines:
        merged = base_text + "\n\n[SUPPLEMENTAL LINES]\n" + "\n".join(extra_lines)
        return merged

    return base_text


def _line_is_informative(line: str) -> bool:
    """
    Check if a line is worth including in merged results.
    Must contain at least one: keyword, ID pattern, date, or label.
    """
    line_lower = line.lower()
    # Has a colon (key-value pair)?
    if ':' in line and len(line) > 5:
        return True
    # Contains a known keyword?
    for kw in ["pan", "aadhaar", "gst", "name", "year", "itr", "date", "account", "ifsc", "tan"]:
        if kw in line_lower:
            return True
    # Contains a PAN-like pattern?
    if re.search(r'[A-Z]{5}[0-9]{4}[A-Z]', line.upper()):
        return True
    # Contains digit sequence?
    if re.search(r'\d{6,}', line):
        return True
    return False


def compute_field_confidence(
    value: Optional[str],
    *,
    is_regex_match: bool = False,
    is_label_anchored: bool = False,
    is_valid_format: bool = False,
    is_corrected: bool = False,
    ocr_score: float = 0.0,
) -> int:
    """
    Compute a confidence score (0-100) for an extracted field.

    Factors:
    - Was it found at all?
    - Did it match a strict regex?
    - Was it label-anchored (found near a known label)?
    - Does it have valid format?
    - Was it corrected (slightly lower confidence)?
    - What was the OCR quality score?

    Returns int 0-100.
    """
    if not value:
        return 0

    confidence = 0

    # Base: it was found
    confidence += 30

    # Format validation
    if is_valid_format:
        confidence += 30

    # Strict regex match
    if is_regex_match:
        confidence += 15

    # Label-anchored (found near a label)
    if is_label_anchored:
        confidence += 15

    # Correction applied (slight penalty: it wasn't perfect)
    if is_corrected:
        confidence -= 5

    # OCR quality contribution (0-10 points)
    ocr_contribution = min(10, int(ocr_score / 20))
    confidence += ocr_contribution

    return max(0, min(100, confidence))
