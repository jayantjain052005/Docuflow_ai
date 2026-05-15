"""
DocuFlow AI - Flask Integration  (production-grade)

Provides:
- /upload endpoint: single-file OCR + classification + routing
- /batch endpoint: multi-file batch processing
- /health endpoint: service health check
- /review endpoint: list files in manual-review queue
- Error handling, file validation, and structured JSON responses

Usage:
    from ocr.flask_integration import create_ocr_blueprint

    app = Flask(__name__)
    ocr_bp = create_ocr_blueprint(
        client_registry=[...],          # your client list
        upload_folder="/tmp/docuflow",  # temp storage for uploads
        cache_dir="/tmp/docuflow_cache",
        workers=4,
    )
    app.register_blueprint(ocr_bp, url_prefix="/ocr")

    # Then POST /ocr/upload with form-data file field "document"
"""

import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Supported file extensions
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
MAX_UPLOAD_SIZE_MB = 50


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _file_size_ok(filepath: str, max_mb: int = MAX_UPLOAD_SIZE_MB) -> bool:
    try:
        return os.path.getsize(filepath) <= max_mb * 1024 * 1024
    except OSError:
        return False


def _error_response(message: str, status_code: int = 400) -> tuple:
    """Build a JSON error response tuple for Flask."""
    from flask import jsonify  # lazy import — don't force Flask at module load time
    return jsonify({"success": False, "error": message}), status_code


def _success_response(data: dict, status_code: int = 200) -> tuple:
    from flask import jsonify
    return jsonify({"success": True, **data}), status_code


def create_ocr_blueprint(
    client_registry: Optional[list[dict]] = None,
    upload_folder: str = "/tmp/docuflow_uploads",
    cache_dir: str = "/tmp/docuflow_ocr_cache",
    workers: int = 4,
):
    """
    Create and return a Flask Blueprint for the OCR API.

    Registers:
      POST   /upload          — single file OCR + routing
      POST   /batch           — multi-file batch OCR + routing
      GET    /health          — service health check
      GET    /cache/stats     — OCR cache statistics
    """
    from flask import Blueprint, request

    from ocr import process_document
    from ocr.batch import BatchProcessor, OCRCache
    from ocr.routing import build_routing_decision, DuplicateDetector

    Path(upload_folder).mkdir(parents=True, exist_ok=True)

    ocr_bp = Blueprint("ocr", __name__)

    # Shared resources (initialised once)
    _cache = OCRCache(cache_dir)
    _batch_processor = BatchProcessor(
        workers=workers,
        cache_dir=cache_dir,
        client_registry=client_registry or [],
    )
    _session_detector = DuplicateDetector()

    # ── /upload ──────────────────────────────────────────────

    @ocr_bp.route("/upload", methods=["POST"])
    def upload():
        """
        Upload a single document for OCR processing.

        Form data:
            document   (file, required)   — the document file
            client_id  (str, optional)    — pre-selected client ID

        Returns JSON with full OCR result and routing decision.
        """
        if "document" not in request.files:
            return _error_response("No file provided. Use field name 'document'.")

        file = request.files["document"]
        if not file.filename:
            return _error_response("Empty filename.")
        if not _allowed_file(file.filename):
            return _error_response(
                f"Unsupported file type '{Path(file.filename).suffix}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # Save to temp file with UUID to prevent collisions
        suffix = Path(file.filename).suffix.lower()
        safe_name = f"{uuid.uuid4().hex}{suffix}"
        tmp_path = os.path.join(upload_folder, safe_name)

        try:
            file.save(tmp_path)
        except OSError as exc:
            logger.error(f"Failed to save upload: {exc}")
            return _error_response("Server error: could not save file.", 500)

        if not _file_size_ok(tmp_path):
            os.unlink(tmp_path)
            return _error_response(
                f"File too large. Maximum size is {MAX_UPLOAD_SIZE_MB} MB."
            )

        t_start = time.monotonic()

        # Check cache first
        cached = _cache.get(tmp_path)
        if cached:
            cached["_from_cache"] = True
            routing = build_routing_decision(
                tmp_path, cached,
                client_registry=client_registry or [],
                duplicate_detector=_session_detector,
            )
            os.unlink(tmp_path)
            return _success_response({
                "ocr_result": _safe_result(cached),
                "routing": routing,
                "elapsed_s": 0.0,
                "from_cache": True,
            })

        # Run OCR
        try:
            ocr_result = process_document(tmp_path)
        except Exception as exc:
            logger.exception(f"OCR failed for '{file.filename}': {exc}")
            os.unlink(tmp_path)
            return _error_response(f"OCR processing failed: {exc}", 500)

        elapsed = round(time.monotonic() - t_start, 3)

        # Cache the result
        _cache.set(tmp_path, ocr_result)

        # Routing decision
        routing = build_routing_decision(
            tmp_path, ocr_result,
            client_registry=client_registry or [],
            duplicate_detector=_session_detector,
        )

        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        logger.info(
            f"Upload: '{file.filename}' → type='{ocr_result.get('document_type')}' "
            f"action='{routing['action']}' elapsed={elapsed}s"
        )

        return _success_response({
            "ocr_result": _safe_result(ocr_result),
            "routing": routing,
            "elapsed_s": elapsed,
            "from_cache": False,
        })

    # ── /batch ───────────────────────────────────────────────

    @ocr_bp.route("/batch", methods=["POST"])
    def batch():
        """
        Upload multiple documents for batch processing.

        Form data:
            documents[]  (files, required) — one or more files

        Returns JSON list, one entry per file.
        """
        files = request.files.getlist("documents[]")
        if not files:
            return _error_response("No files provided. Use field name 'documents[]'.")

        saved_paths: list[tuple[str, str]] = []  # (tmp_path, original_name)
        for file in files:
            if not file.filename or not _allowed_file(file.filename):
                logger.warning(f"Skipping unsupported file: '{file.filename}'")
                continue
            suffix = Path(file.filename).suffix.lower()
            safe_name = f"{uuid.uuid4().hex}{suffix}"
            tmp_path = os.path.join(upload_folder, safe_name)
            try:
                file.save(tmp_path)
                if _file_size_ok(tmp_path):
                    saved_paths.append((tmp_path, file.filename))
                else:
                    os.unlink(tmp_path)
                    logger.warning(f"File '{file.filename}' too large, skipped.")
            except OSError as exc:
                logger.error(f"Failed to save '{file.filename}': {exc}")

        if not saved_paths:
            return _error_response("No valid files could be saved.")

        t_start = time.monotonic()
        tmp_files = [p for p, _ in saved_paths]

        try:
            results = _batch_processor.process_batch(tmp_files, use_routing=True)
        except Exception as exc:
            logger.exception(f"Batch processing failed: {exc}")
            for p in tmp_files:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            return _error_response(f"Batch processing failed: {exc}", 500)

        elapsed = round(time.monotonic() - t_start, 3)

        # Clean up temp files
        for p in tmp_files:
            try:
                os.unlink(p)
            except OSError:
                pass

        # Attach original filenames to results
        path_to_name = {p: n for p, n in saved_paths}
        for r in results:
            r["original_filename"] = path_to_name.get(r.get("file", ""), "")

        return _success_response({
            "results": [_safe_batch_result(r) for r in results],
            "total": len(results),
            "elapsed_s": elapsed,
        })

    # ── /health ──────────────────────────────────────────────

    @ocr_bp.route("/health", methods=["GET"])
    def health():
        """Health check — verifies OCR dependencies are available."""
        checks: dict[str, str] = {}

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            checks["tesseract"] = "ok"
        except Exception as exc:
            checks["tesseract"] = f"error: {exc}"

        try:
            import cv2
            checks["opencv"] = f"ok (v{cv2.__version__})"
        except ImportError:
            checks["opencv"] = "missing"

        try:
            import pdfplumber
            checks["pdfplumber"] = "ok"
        except ImportError:
            checks["pdfplumber"] = "missing"

        all_ok = all(v == "ok" or v.startswith("ok") for v in checks.values())
        status_code = 200 if all_ok else 503
        from flask import jsonify
        return jsonify({
            "status": "healthy" if all_ok else "degraded",
            "checks": checks,
            "cache_stats": _cache.stats,
        }), status_code

    # ── /cache/stats ─────────────────────────────────────────

    @ocr_bp.route("/cache/stats", methods=["GET"])
    def cache_stats():
        return _success_response({"cache": _cache.stats})

    return ocr_bp


# ─────────────────────────────────────────────
# RESPONSE HELPERS
# ─────────────────────────────────────────────

def _safe_result(ocr_result: dict) -> dict:
    """
    Strip internal debug fields from OCR result before sending to client.
    Ensures response is JSON-serialisable.
    """
    safe = {k: v for k, v in ocr_result.items() if k not in ("_debug", "raw_text")}
    # Truncate raw_text for the response (full text is kept server-side for audit)
    if "raw_text" in ocr_result:
        safe["text_preview"] = ocr_result.get("raw_text", "")[:500]
    return safe


def _safe_batch_result(r: dict) -> dict:
    """Prepare a single batch result for JSON response."""
    return {
        "file": r.get("file"),
        "original_filename": r.get("original_filename", ""),
        "status": r.get("status"),
        "elapsed_s": r.get("elapsed_s", 0.0),
        "document_type": r.get("document_type"),
        "document_confidence": r.get("document_confidence"),
        "ocr_score": r.get("ocr_score"),
        "detected_name": r.get("detected_name"),
        "year": r.get("year"),
        "important_ids": r.get("important_ids"),
        "action": r.get("action"),
        "action_reason": r.get("action_reason"),
        "routing": r.get("routing"),
        "error": r.get("error"),
    }
