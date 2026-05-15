"""
DocuFlow AI - Document Routing Engine  (production-grade)

Provides:
- Google Drive folder mapping by document type + client
- Client matching from extracted metadata
- Duplicate document detection (hash-based)
- Upload pipeline integration helpers
- Structured routing decisions with audit trail
"""

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GOOGLE DRIVE FOLDER MAPPING
# ─────────────────────────────────────────────

# Map document type labels → Drive subfolder names.
# These must match the actual folder names in your Drive structure.
DRIVE_FOLDER_MAP: dict[str, str] = {
    "PAN Card":             "PAN Cards",
    "Aadhaar Card":         "Aadhaar Cards",
    "ITR Acknowledgement":  "ITR Acknowledgements",
    "GST Certificate":      "GST Certificates",
    "Bank Statement":       "Bank Statements",
    "Salary Slip":          "Salary Slips",
    "Invoice":              "Invoices",
    "Form 16":              "Form 16",
    "Cheque":               "Cheques",
    "Passbook":             "Passbooks",
    "Balance Sheet":        "Balance Sheets",
    "Other":                "Uncategorised",
}

# Minimum classification confidence required to route to a typed folder.
# Below this, files go to "Uncategorised".
MIN_ROUTING_CONFIDENCE = 60  # %

# Minimum OCR score required for any routing decision.
# Below this, the file is flagged for manual review.
MIN_OCR_SCORE_FOR_ROUTING = 20.0


def get_drive_folder(
    document_type: str,
    document_confidence: int,
    client_folder_id: Optional[str] = None,
    ocr_score: float = 100.0,
) -> dict:
    """
    Determine the Google Drive folder for a document.

    Args:
        document_type:       Classified document type string.
        document_confidence: Classification confidence (0-100).
        client_folder_id:    Drive folder ID for this client (root of client tree).
        ocr_score:           OCR quality score; low scores trigger manual review.

    Returns:
        {
            "folder_name":    str,    # subfolder name within client folder
            "folder_path":    str,    # full logical path (client/subfolder)
            "needs_review":   bool,   # flag for manual review queue
            "review_reason":  str,    # reason for review flag (empty if none)
            "client_root_id": str|None,
        }
    """
    review_reasons: list[str] = []

    if ocr_score < MIN_OCR_SCORE_FOR_ROUTING:
        review_reasons.append(f"low OCR score ({ocr_score:.1f})")

    if document_confidence < MIN_ROUTING_CONFIDENCE:
        review_reasons.append(
            f"low classification confidence ({document_confidence}%)"
        )
        folder_name = DRIVE_FOLDER_MAP.get("Other", "Uncategorised")
    else:
        folder_name = DRIVE_FOLDER_MAP.get(document_type, "Uncategorised")
        if folder_name == "Uncategorised":
            review_reasons.append(f"unrecognised document type '{document_type}'")

    folder_path = (
        f"[Client Root]/{folder_name}"
        if not client_folder_id
        else f"{client_folder_id}/{folder_name}"
    )

    needs_review = bool(review_reasons)
    if needs_review:
        logger.warning(
            f"Document flagged for review: {'; '.join(review_reasons)}"
        )

    return {
        "folder_name": folder_name,
        "folder_path": folder_path,
        "needs_review": needs_review,
        "review_reason": "; ".join(review_reasons),
        "client_root_id": client_folder_id,
    }


# ─────────────────────────────────────────────
# CLIENT MATCHING
# ─────────────────────────────────────────────

def match_client_by_ids(
    extracted_ids: dict,
    client_registry: list[dict],
) -> dict:
    """
    Match a document to a client using extracted IDs.

    Matching priority (highest to lowest):
    1. PAN  (unique, very reliable)
    2. GSTIN (unique per registration)
    3. TAN  (unique per deductor)
    4. Aadhaar (only if confidence ≥ 75)

    Args:
        extracted_ids:   Dict from metadata extraction:
                         {"pan": {"value": ..., "confidence": ...}, ...}
        client_registry: List of client dicts, each with:
                         {"client_id": str, "name": str,
                          "pan": str|None, "gstin": str|None,
                          "tan": str|None, "aadhaar": str|None,
                          "drive_folder_id": str|None}

    Returns:
        {
            "matched":          bool,
            "client_id":        str|None,
            "client_name":      str|None,
            "match_field":      str|None,  # which field matched
            "match_confidence": int,       # 0-100
            "drive_folder_id":  str|None,
        }
    """
    if not client_registry:
        return _no_match("empty client registry")

    pan = extracted_ids.get("pan", {})
    gstin = extracted_ids.get("gstin", {})
    tan = extracted_ids.get("tan", {})
    aadhaar = extracted_ids.get("aadhaar", {})

    pan_val = (pan.get("value") or "").upper().strip()
    gstin_val = (gstin.get("value") or "").upper().strip()
    tan_val = (tan.get("value") or "").upper().strip()
    aadhaar_val = re.sub(r'\D', '', aadhaar.get("value") or "")
    aadhaar_conf = aadhaar.get("confidence", 0)

    for client in client_registry:
        # PAN match
        if pan_val and client.get("pan", "").upper() == pan_val:
            return _build_match(client, "PAN", 95)
        # GSTIN match
        if gstin_val and client.get("gstin", "").upper() == gstin_val:
            return _build_match(client, "GSTIN", 90)
        # TAN match
        if tan_val and client.get("tan", "").upper() == tan_val:
            return _build_match(client, "TAN", 88)
        # Aadhaar match — only use if confidence is high enough
        if aadhaar_val and aadhaar_conf >= 75:
            client_aadhaar = re.sub(r'\D', '', client.get("aadhaar") or "")
            if client_aadhaar and client_aadhaar == aadhaar_val:
                return _build_match(client, "Aadhaar", 82)

    return _no_match("no ID match found in registry")


def _build_match(client: dict, field: str, confidence: int) -> dict:
    logger.info(
        f"Client matched: '{client.get('name')}' "
        f"via {field} (conf={confidence}%)"
    )
    return {
        "matched": True,
        "client_id": client.get("client_id"),
        "client_name": client.get("name"),
        "match_field": field,
        "match_confidence": confidence,
        "drive_folder_id": client.get("drive_folder_id"),
    }


def _no_match(reason: str) -> dict:
    logger.info(f"No client match: {reason}")
    return {
        "matched": False,
        "client_id": None,
        "client_name": None,
        "match_field": None,
        "match_confidence": 0,
        "drive_folder_id": None,
    }


# ─────────────────────────────────────────────
# DUPLICATE DETECTION
# ─────────────────────────────────────────────

def compute_document_hash(filepath: str) -> Optional[str]:
    """
    Compute SHA-256 hash of a document file.

    Used for exact duplicate detection.  Two files with identical
    hashes are bitwise duplicates (same scan / same upload).
    """
    try:
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, IOError) as exc:
        logger.warning(f"Cannot hash file '{filepath}': {exc}")
        return None


def compute_content_fingerprint(ocr_result: dict) -> str:
    """
    Compute a content-level fingerprint from extracted metadata.

    Two different scans of the same document (different resolution,
    slightly different crop) will produce identical fingerprints if
    they share the same key IDs and assessment year.

    This catches semantic duplicates that a hash check would miss.

    Returns a stable string fingerprint.
    """
    ids = ocr_result.get("important_ids", {})
    parts = [
        ocr_result.get("document_type", ""),
        ids.get("pan", {}).get("value") or "",
        re.sub(r'\D', '', ids.get("aadhaar", {}).get("value") or ""),
        ids.get("gstin", {}).get("value") or "",
        ids.get("tan", {}).get("value") or "",
        ocr_result.get("year", {}).get("value") or "",
    ]
    fingerprint_str = "|".join(parts).upper()
    return hashlib.md5(fingerprint_str.encode()).hexdigest()


class DuplicateDetector:
    """
    In-memory duplicate store for a processing session.

    For production, replace the internal sets with a Redis cache or
    database table keyed on (client_id, fingerprint).

    Usage:
        detector = DuplicateDetector()
        status = detector.check(filepath, ocr_result)
        if status["is_duplicate"]:
            # skip upload
    """

    def __init__(self) -> None:
        self._file_hashes: dict[str, str] = {}       # hash → original filepath
        self._content_prints: dict[str, str] = {}     # fingerprint → original filepath

    def check(self, filepath: str, ocr_result: dict) -> dict:
        """
        Check whether this file is a duplicate.

        Returns:
        {
            "is_duplicate":  bool,
            "duplicate_type": "exact" | "semantic" | None,
            "original_file": str | None,  # path of first-seen duplicate
        }
        """
        file_hash = compute_document_hash(filepath)
        if file_hash:
            if file_hash in self._file_hashes:
                original = self._file_hashes[file_hash]
                logger.warning(
                    f"Exact duplicate detected: '{filepath}' matches '{original}'"
                )
                return {
                    "is_duplicate": True,
                    "duplicate_type": "exact",
                    "original_file": original,
                }
            self._file_hashes[file_hash] = filepath

        content_fp = compute_content_fingerprint(ocr_result)
        if content_fp in self._content_prints:
            original = self._content_prints[content_fp]
            logger.warning(
                f"Semantic duplicate detected: '{filepath}' matches '{original}'"
            )
            return {
                "is_duplicate": True,
                "duplicate_type": "semantic",
                "original_file": original,
            }
        self._content_prints[content_fp] = filepath

        return {"is_duplicate": False, "duplicate_type": None, "original_file": None}

    def reset(self) -> None:
        """Clear the duplicate store (e.g. at start of each batch job)."""
        self._file_hashes.clear()
        self._content_prints.clear()


# ─────────────────────────────────────────────
# FULL ROUTING DECISION
# ─────────────────────────────────────────────

def build_routing_decision(
    filepath: str,
    ocr_result: dict,
    client_registry: Optional[list[dict]] = None,
    duplicate_detector: Optional[DuplicateDetector] = None,
) -> dict:
    """
    Produce a complete routing decision for a processed document.

    Combines:
    - Client matching
    - Drive folder determination
    - Duplicate detection
    - Audit trail fields

    Args:
        filepath:             Path to the source document file.
        ocr_result:           Output of process_document().
        client_registry:      Optional list of client dicts for matching.
        duplicate_detector:   Optional DuplicateDetector instance.

    Returns:
        {
            "file":                str,
            "document_type":       str,
            "document_confidence": int,
            "ocr_score":           float,
            "client":              {...},     # from match_client_by_ids
            "drive":               {...},     # from get_drive_folder
            "duplicate":           {...},     # from DuplicateDetector.check
            "action":              "upload" | "review" | "skip",
            "action_reason":       str,
            "timestamp":           float,
        }
    """
    doc_type = ocr_result.get("document_type", "Other")
    doc_conf = ocr_result.get("document_confidence", 0)
    ocr_score = ocr_result.get("ocr_score", 0.0)
    extracted_ids = ocr_result.get("important_ids", {})

    # Client match
    client_match = match_client_by_ids(
        extracted_ids,
        client_registry or [],
    )

    # Drive folder
    drive_info = get_drive_folder(
        doc_type,
        doc_conf,
        client_folder_id=client_match.get("drive_folder_id"),
        ocr_score=ocr_score,
    )

    # Duplicate check
    if duplicate_detector is not None:
        dup_check = duplicate_detector.check(filepath, ocr_result)
    else:
        dup_check = {"is_duplicate": False, "duplicate_type": None, "original_file": None}

    # Action determination
    if dup_check["is_duplicate"]:
        action = "skip"
        action_reason = f"Duplicate ({dup_check['duplicate_type']}): matches {dup_check['original_file']}"
    elif drive_info["needs_review"] or not client_match["matched"]:
        action = "review"
        reasons = []
        if drive_info["needs_review"]:
            reasons.append(drive_info["review_reason"])
        if not client_match["matched"]:
            reasons.append("no client match")
        action_reason = "; ".join(reasons)
    else:
        action = "upload"
        action_reason = (
            f"Matched client '{client_match['client_name']}' "
            f"via {client_match['match_field']}"
        )

    decision = {
        "file": str(filepath),
        "document_type": doc_type,
        "document_confidence": doc_conf,
        "ocr_score": ocr_score,
        "client": client_match,
        "drive": drive_info,
        "duplicate": dup_check,
        "action": action,
        "action_reason": action_reason,
        "timestamp": time.time(),
    }

    logger.info(
        f"Routing: file='{Path(filepath).name}' type='{doc_type}' "
        f"action='{action}' folder='{drive_info['folder_name']}' "
        f"client='{client_match.get('client_name')}'"
    )
    return decision
