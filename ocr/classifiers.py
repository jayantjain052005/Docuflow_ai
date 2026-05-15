"""
DocuFlow AI - Document Type Classifier

Classifies documents using rule-based semantic scoring with confidence.

Strategy:
- Score text against keyword maps for each document type
- Apply structural signals (PAN, Aadhaar, AY, GSTIN presence)
- Apply layout signals (table detection, key-value structure)
- Normalize scores to get confidence percentages
- Return top classification + all scores for audit
"""

import re
import logging
from typing import Optional

from ocr.constants import (
    CLASSIFICATION_KEYWORDS,
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
)
from ocr.regex_patterns import (
    PAN_STRICT,
    AADHAAR_FORMATTED,
    AADHAAR_PLAIN,
    GSTIN_STRICT,
    AY_PATTERN,
    AY_STANDALONE,
    ITR_TYPE_PATTERN,
    TAN_STRICT,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# NAME EXTRACTION BLOCKLIST
# Phrases that appear near PAN/ID fields in Indian tax documents
# but are NOT person names. Used by pan_proximate and other
# name heuristics to discard false positives.
# ─────────────────────────────────────────────

_NAME_BLOCKLIST: frozenset[str] = frozenset({
    # ITR / Form 16 field labels
    "of premises",
    "address of premises",
    "name and address",
    "name and address of premises",
    "place of business",
    "registered office",
    "principal place",
    "principal place of business",
    # "Of Premises" OCR fragments — the most common false positive.
    # ITR docs contain "Name and Address of Premises"; OCR grabs the
    # tail "Of Premises" as if it were a name value.
    "of",                           # bare "of" (single word, always noise)
    "premises",
    "and address",
    "address",
    # Generic address words that OCR sometimes grabs
    "flat no",
    "house no",
    "building",
    "ward",
    "pin code",
    "pincode",
    "state",
    "city",
    "district",
    "taluka",
    "tehsil",
    "village",
    # Document metadata labels
    "date",
    "assessment year",
    "acknowledgement",
    "acknowledgement number",
    "income tax",
    "income tax department",
    "government of india",
    "return of income",
    "see rule",
    "see rule 12",
    "form no",
    "itr",
    "rule",
    # Single-word prepositions / articles that are never names
    "the",
    "and",
    "for",
    "in",
    "to",
    "from",
    "by",
    "with",
    "on",
    "at",
    "as",
    "an",
    "a",
    # Common OCR garbage fragments seen in production
    "le mute",
    "ptvnee",
    "ptvnee see rule",
    "see",
    "nil",
    "na",
    "n/a",
    "none",
    "null",
    # ITR structural labels that appear near "name" fields
    "verification",
    "filing date",
    "e-filing",
    "efiling",
    "filed",
    "tax payable",
    "total income",
    "refund",
    "gross total",
    "net tax",
    "bank account",
    "account number",
    # Bank statement headings that are not person names
    "account summary",
    "account statement",
    "statement summary",
    "transaction summary",
    "customer id",
    "account details",
})


def _is_blocklisted_name(candidate: str) -> bool:
    """
    Return True if the candidate string is a known non-name phrase
    (a document label, address fragment, or OCR artefact).

    Comparison is case-insensitive and strips leading/trailing whitespace.
    """
    return candidate.strip().lower() in _NAME_BLOCKLIST


# ─────────────────────────────────────────────
# STRUCTURAL BONUS SIGNALS
# Applied on top of keyword scores
# ─────────────────────────────────────────────

def _compute_structural_bonuses(text: str, text_upper: str) -> dict[str, int]:
    """
    Compute structural bonus scores for each document type
    based on the presence of ID patterns and structural clues.

    Returns dict of {doc_type: bonus_score}
    """
    bonuses: dict[str, int] = {dt: 0 for dt in CLASSIFICATION_KEYWORDS}

    has_pan = bool(PAN_STRICT.search(text_upper))
    has_aadhaar = bool(AADHAAR_FORMATTED.search(text) or AADHAAR_PLAIN.search(text))
    has_gstin = bool(GSTIN_STRICT.search(text_upper))
    has_ay = bool(AY_PATTERN.search(text) or AY_STANDALONE.search(text))
    has_tan = bool(TAN_STRICT.search(text_upper))
    has_itr = bool(ITR_TYPE_PATTERN.search(text))

    # Count key-value pairs (colon-separated)
    kv_count = len(re.findall(r'\b\w[\w\s]{2,20}:\s*\S', text))

    # Count table-like rows (rows with multiple tab/space-separated numbers)
    table_row_count = len(re.findall(r'[\d,.]+\s{2,}[\d,.]+', text))

    # ── PAN Card ──
    if has_pan:
        bonuses[DOCTYPE_PAN_CARD] += 10
    if has_aadhaar:
        # If has both PAN and Aadhaar, more likely PAN card or Aadhaar card
        bonuses[DOCTYPE_PAN_CARD] += 5

    # ── Aadhaar Card ──
    if has_aadhaar:
        bonuses[DOCTYPE_AADHAAR] += 20
    if has_pan and has_aadhaar:
        bonuses[DOCTYPE_AADHAAR] += 5

    # ── ITR Acknowledgement ──
    if has_pan:
        bonuses[DOCTYPE_ITR_ACK] += 10
    if has_ay:
        bonuses[DOCTYPE_ITR_ACK] += 20
    if has_itr:
        bonuses[DOCTYPE_ITR_ACK] += 25
    if kv_count >= 5:  # ITRs have many key-value pairs
        bonuses[DOCTYPE_ITR_ACK] += 8

    # ── GST Certificate ──
    if has_gstin:
        bonuses[DOCTYPE_GST_CERT] += 30
    if has_pan:
        bonuses[DOCTYPE_GST_CERT] += 5

    # ── Bank Statement ──
    if table_row_count >= 5:  # Many numeric rows = table = transactions
        bonuses[DOCTYPE_BANK_STMT] += 15
    if kv_count >= 3:
        bonuses[DOCTYPE_BANK_STMT] += 5

    # ── Salary Slip ──
    if has_pan:
        bonuses[DOCTYPE_SALARY_SLIP] += 5
    if table_row_count >= 3:
        bonuses[DOCTYPE_SALARY_SLIP] += 8

    # ── Form 16 ──
    if has_tan:
        bonuses[DOCTYPE_FORM16] += 20
    if has_pan:
        bonuses[DOCTYPE_FORM16] += 10
    if has_ay:
        bonuses[DOCTYPE_FORM16] += 10

    # ── Invoice ──
    if has_gstin:
        bonuses[DOCTYPE_INVOICE] += 10

    # ── Balance Sheet ──
    if table_row_count >= 3:
        bonuses[DOCTYPE_BALANCE_SHEET] += 8
    if "balance sheet" in text_upper.lower():
        bonuses[DOCTYPE_BALANCE_SHEET] += 20

    return bonuses


def classify_document(text: str, ocr_score: float = 0.0) -> dict:
    """
    Classify a document from its OCR text.

    Returns:
    {
        "document_type": str,
        "document_confidence": int (0-100),
        "all_scores": dict[str, int]
    }
    """
    if not text or len(text.strip()) < 20:
        return {
            "document_type": DOCTYPE_OTHER,
            "document_confidence": 0,
            "all_scores": {},
        }

    text_upper = text.upper()

    # ── Keyword scoring ──
    scores: dict[str, int] = {}
    for doc_type, keywords in CLASSIFICATION_KEYWORDS.items():
        kw_score = 0
        for keyword, weight in keywords:
            if keyword.lower() in text.lower():
                kw_score += weight
        scores[doc_type] = kw_score

    # ── Structural bonuses ──
    bonuses = _compute_structural_bonuses(text, text_upper)
    for doc_type in scores:
        scores[doc_type] += bonuses.get(doc_type, 0)

    # ── Find best match ──
    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    # If no score is meaningful, classify as Other
    if best_score < 15:
        logger.info(f"Classification: scores too low (best={best_score}), returning Other")
        return {
            "document_type": DOCTYPE_OTHER,
            "document_confidence": max(5, int(best_score)),
            "all_scores": scores,
        }

    # ── Confidence: normalize against total ──
    total_score = sum(max(s, 0) for s in scores.values())
    if total_score > 0:
        raw_confidence = (best_score / total_score) * 100
    else:
        raw_confidence = 0.0

    # Amplify confidence: apply a steepening curve
    # (documents are usually clearly one type or another)
    confidence = min(98, int(raw_confidence * 1.5))

    # But cap at 60 if ocr_score is low (unreliable OCR)
    if ocr_score < 20:
        confidence = min(confidence, 60)

    logger.info(
        f"Classification: '{best_type}' confidence={confidence}% "
        f"raw_score={best_score} all_scores={scores}"
    )

    return {
        "document_type": best_type,
        "document_confidence": confidence,
        "all_scores": scores,
    }


def refine_classification(
    classification: dict,
    extracted_ids: dict,
    text: str,
) -> dict:
    """
    Post-extraction refinement of classification.

    After extracting IDs and metadata, we can refine the classification
    if IDs strongly suggest a specific document type — BUT only when the
    initial classification is weak or ambiguous.

    Rules:
    - Never override a high-confidence classification (>= 75%) based on a
      single ID signal alone. ITR forms routinely contain a masked Aadhaar
      and/or PAN, so finding those IDs is not sufficient evidence to
      reclassify an already-confident result.
    - Only override when the classifier score for the proposed new type
      clearly dominates the existing type's score (ratio >= 3×), or when
      the current classification is "Other" / low-confidence.
    """
    doc_type = classification["document_type"]
    confidence = classification["document_confidence"]
    all_scores = classification.get("all_scores", {})

    pan = extracted_ids.get("pan", {}).get("value")
    aadhaar = extracted_ids.get("aadhaar", {}).get("value")
    gstin = extracted_ids.get("gstin", {}).get("value")

    text_lower = text.lower()

    # ── Aadhaar refinement ──
    # Only reclassify to Aadhaar if:
    #   1. An Aadhaar number was extracted AND the document mentions aadhaar/uidai
    #   2. The current classification is not already one of the types that
    #      legitimately contain an Aadhaar reference (ITR, Form 16, Salary Slip)
    #   3. The current classification confidence is low (< 75%), AND
    #      the Aadhaar keyword score strongly beats the current type's score
    #      (aadhaar_score > current_score / 3).  A 3× lead by the winner
    #      means Aadhaar is not a plausible alternative.
    if aadhaar and doc_type not in (
        DOCTYPE_AADHAAR,
        DOCTYPE_PAN_CARD,
        DOCTYPE_FORM16,
        DOCTYPE_SALARY_SLIP,
        DOCTYPE_ITR_ACK,   # ← ITR forms legitimately carry masked Aadhaar
    ):
        if "aadhaar" in text_lower or "uidai" in text_lower:
            current_score = all_scores.get(doc_type, 0)
            aadhaar_score = all_scores.get(DOCTYPE_AADHAAR, 0)

            # Guard: don't override when current classification is already
            # strong, or when the Aadhaar keyword score is not competitive.
            already_confident = confidence >= 75
            aadhaar_not_competitive = current_score >= aadhaar_score * 3

            if already_confident or aadhaar_not_competitive:
                logger.info(
                    f"Skipping Aadhaar refinement: "
                    f"confidence={confidence}% current_score={current_score} "
                    f"aadhaar_score={aadhaar_score} — keeping '{doc_type}'"
                )
                return classification

            logger.info("Refining classification → Aadhaar Card (Aadhaar found, weak existing type)")
            return {
                **classification,
                "document_type": DOCTYPE_AADHAAR,
                "document_confidence": max(confidence, 70),
            }

    # ── GST refinement ──
    # Only trigger when current type is genuinely undecided (Other).
    if gstin and doc_type == DOCTYPE_OTHER:
        if "certificate" in text_lower or "registration" in text_lower:
            return {
                **classification,
                "document_type": DOCTYPE_GST_CERT,
                "document_confidence": 65,
            }
        if "invoice" in text_lower:
            return {
                **classification,
                "document_type": DOCTYPE_INVOICE,
                "document_confidence": 65,
            }

    # ── ITR refinement ──
    # Promote from Other when PAN + AY + ITR type all present.
    if doc_type == DOCTYPE_OTHER and pan:
        has_ay = bool(AY_PATTERN.search(text) or AY_STANDALONE.search(text))
        has_itr = bool(ITR_TYPE_PATTERN.search(text))
        if has_ay and has_itr:
            logger.info(
                "Refining classification → ITR Acknowledgement "
                "(PAN + AY + ITR type found)"
            )
            return {
                **classification,
                "document_type": DOCTYPE_ITR_ACK,
                "document_confidence": 72,
            }

    # ── Form 16 refinement ──
    # TAN is a strong Form 16 signal; only override if not already Form 16.
    tan_found = bool(TAN_STRICT.search(text.upper()))
    if tan_found and "form" in text_lower and "16" in text:
        if doc_type not in (DOCTYPE_FORM16,):
            return {
                **classification,
                "document_type": DOCTYPE_FORM16,
                "document_confidence": max(confidence, 70),
            }

    return classification


def is_valid_extracted_name(name: str) -> bool:
    """
    Return True if the extracted name candidate looks like a real person name
    and is not a known document boilerplate phrase or OCR artefact.

    Use this in name extraction strategies (pan_proximate, top_heuristic,
    etc.) to filter candidates before committing to them.

    Examples that return False:
        "Of Premises", "See Rule", "Assessment Year", "Le Mute", "Nil"
        "Of", "Premises", "And Address", "Ptvnee See Rule"

    Examples that return True:
        "Gurmeet Singh", "Rajesh Kumar", "Priya Nair", "Jayant Jain"
    """
    if not name:
        return False
    cleaned = name.strip()
        
    bad_tokens = {
        "signature",
        "counter",
        "trp",
        "premises",
        "address",
        "rule",
        "acknowledgement",
        "department",
        "verification",
        "office",
        "processing",
        "centre",
        "account",
        "statement",
        "transaction",
        "summary",
    }

    tokens = cleaned.lower().split()

    if any(token in bad_tokens for token in tokens):
        return False

    if not cleaned:
        return False

    # Reject blocklisted phrases (case-insensitive)
    if _is_blocklisted_name(cleaned):
        return False

    # Reject very short strings — likely noise or a single label word
    if len(cleaned) < 4:
        return False

    # Reject strings that are mostly digits
    digit_ratio = sum(c.isdigit() for c in cleaned) / max(len(cleaned), 1)
    if digit_ratio > 0.4:
        return False

    # Reject strings that start with a preposition or article.
    # "Of Premises", "And Address", "In The", "Of The" are all boilerplate.
    _LEADING_STOPWORDS = frozenset({
        "of", "and", "the", "in", "to", "for", "from", "by",
        "with", "on", "at", "as", "an", "a", "see", "per",
    })
    first_word = cleaned.split()[0].lower().rstrip('.,:-')
    if first_word in _LEADING_STOPWORDS:
        return False

    # Reject strings that are entirely uppercase single words shorter than 4 chars
    # (OCR artefacts like "PAN", "DOB", "ITR" that slip through)
    words = cleaned.split()
    if len(words) == 1 and len(cleaned) < 4:
        return False

    # A person name must have at least one word that is 2+ alphabetic characters
    has_real_word = any(
        sum(c.isalpha() for c in w) >= 2
        for w in words
    )
    if not has_real_word:
        return False

    # Reject if the entire string is a known OCR garbage pattern:
    # sequences with fewer than 2 distinct alpha characters (e.g. "Ptvnee")
    alpha_chars = [c.lower() for c in cleaned if c.isalpha()]
    if len(alpha_chars) < 3:
        return False

    return True
