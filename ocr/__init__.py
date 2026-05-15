"""
DocuFlow AI - OCR Package

Public API:
    process_document(filepath) → dict

The main entry point that orchestrates:
1. Text extraction (multi-pass OCR)
2. OCR correction
3. Document classification
4. Metadata extraction
5. Returns standardized output JSON
"""

import logging
# f?rom pathlib import Path
 

from ocr.extractor import extract_raw_text
from ocr.classifiers import classify_document, refine_classification
from ocr.metadata import extract_all_metadata
from ocr.utils import setup_logging

logger = logging.getLogger(__name__)


def process_document(filepath: str, verbose: bool = False) -> dict:
    """
    Full document processing pipeline.

    Args:
        filepath: Path to document (PDF, JPG, PNG, JPEG)
        verbose:  Enable debug logging

    Returns:
        Standardized metadata dict:
        {
            "document_type": str,
            "document_confidence": int,
            "detected_name": {"value": str|None, "confidence": int},
            "year": {"value": str|None, "confidence": int},
            "important_ids": {
                "pan":    {"value": str|None, "confidence": int},
                "aadhaar":{"value": str|None, "confidence": int},
                "gstin":  {"value": str|None, "confidence": int},
                "tan":    {"value": str|None, "confidence": int},
                "ifsc":   {"value": str|None, "confidence": int},
            },
            "supplemental": { ... },
            "summary": str,
            "raw_text": str,
            "ocr_score": float,
            "ocr_method": str,
        }
    """
    if verbose:
        setup_logging(logging.DEBUG)
    else:
        setup_logging(logging.INFO)

    logger.info(f"Processing: '{filepath}'")

    # ── Step 1: Extract text ──
    extraction = extract_raw_text(filepath)
    text = extraction.get("text", "")
    raw_text = extraction.get("raw_text", "")
    ocr_score = extraction.get("score", 0.0)
    ocr_method = extraction.get("method", "unknown")

    if not text.strip():
        logger.warning("No text extracted from document.")

    # ── Step 2: Classify document ──
    classification = classify_document(text, ocr_score=ocr_score)

    # ── Step 3: Extract metadata ──
    metadata = extract_all_metadata(text, ocr_score=ocr_score)

    # ── Step 4: Refine classification using extracted IDs ──
    classification = refine_classification(
        classification,
        metadata.get("important_ids", {}),
        text,
    )

    # ── Step 5: Build summary ──
    summary = _build_summary(classification, metadata)

    # ── Assemble final output ──
    output = {
        "document_type": classification["document_type"],
        "document_confidence": classification["document_confidence"],
        "detected_name": metadata["detected_name"],
        "year": metadata["year"],
        "important_ids": metadata["important_ids"],
        "supplemental": metadata.get("supplemental", {}),
        "summary": summary,
        "raw_text": text,  # Corrected text (use for search/audit)
        "ocr_score": round(ocr_score, 2),
        "ocr_method": ocr_method,
        "_debug": {
            "classification_scores": classification.get("all_scores", {}),
            "ocr_config": extraction.get("ocr_config", ""),
            "page_count": extraction.get("page_count", 1),
        },
    }

    logger.info(
        f"Result: type='{output['document_type']}' "
        f"conf={output['document_confidence']}% "
        f"name='{output['detected_name'].get('value')}' "
        f"PAN='{output['important_ids']['pan'].get('value')}'"
    )

    return output


def _build_summary(classification: dict, metadata: dict) -> str:
    """Build a human-readable summary of the extracted document info."""
    parts = []

    doc_type = classification.get("document_type", "Unknown")
    doc_conf = classification.get("document_confidence", 0)
    parts.append(f"Document Type: {doc_type} (confidence: {doc_conf}%)")

    name = metadata.get("detected_name", {}).get("value")
    if name:
        parts.append(f"Name: {name}")

    ids = metadata.get("important_ids", {})

    pan = ids.get("pan", {}).get("value")
    if pan:
        parts.append(f"PAN: {pan}")

    aadhaar = ids.get("aadhaar", {}).get("value")
    if aadhaar:
        parts.append(f"Aadhaar: {aadhaar}")

    gstin = ids.get("gstin", {}).get("value")
    if gstin:
        parts.append(f"GSTIN: {gstin}")

    ay = metadata.get("year", {}).get("value")
    if ay:
        parts.append(f"Assessment Year: {ay}")

    supp = metadata.get("supplemental", {})
    itr = supp.get("itr_type", {}).get("value")
    if itr:
        parts.append(f"ITR Type: {itr}")

    return " | ".join(parts)
