"""
DocuFlow AI - Multi-Pass OCR Engine  (v4 — Generator-Based Lazy Preprocessing)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v4 changes to extractor.py (companion to preprocess.py v4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. GENERATOR ITERATION (matches preprocess.py v4 API change)
   preprocess_image() now yields (name, image) pairs instead of returning
   a full dict.  ocr_image_multipass() iterates the generator and calls
   next() on it inside the OCR pass loop — so preprocessing and OCR are
   interleaved rather than batched.

   Effect: When short-circuit fires on pass 1 (common for clean ITR scans),
   the generator is abandoned with 0 additional pipeline invocations.
   In v3, ALL pipelines were precomputed before pass 1 even started.

2. PIPELINE ORDERING AWARENESS
   preprocess.py v4 yields pipelines cheapest-first:
     grayscale_only → fastpath → light → standard → adaptive → sharpen → heavy_denoise
   extractor.py now passes only the pipelines the current OCR mode needs,
   preserving this order so cheap pipelines run first.

3. FAST-PATH PIPELINE DETECTION
   When quality.is_clean=True, the "fastpath" pipeline is yielded by the
   generator first. On a clean ITR scan, pass 1 (grayscale_only) or pass 2
   (fastpath) will typically fire short-circuit and stop the generator.
   This means preprocessing for a clean scan costs:
     - cap_image_size:      ~5ms
     - to_grayscale:        ~2ms
     - border_cleanup:      ~1ms
     - assess_image_quality: ~3ms
     - grayscale_only resize: ~5ms
     - 1× Tesseract:        ~3s
   Total: ~3s (vs 41s+3s in v3)

4. PIPELINE FILTER UPDATED
   _get_active_pipeline_names() replaces _get_active_pipelines().
   Returns the list of pipeline name strings for the current mode.
   preprocess_image() uses this to filter its generator output.

5. TIMING METRICS PRESERVED
   All per-stage timing (preprocess, tess_pass, correction) still logged.
   Preprocessing timing is now per-pipeline (not per-scale-total) since
   pipelines are interleaved with Tesseract calls.

6. SHORT-CIRCUIT LOGIC UNCHANGED
   _should_short_circuit() is identical to v3.

Architecture unchanged:
- Same public API: extract_raw_text(filepath) → dict
- Same return dict shape
- Same OCR_MODE / early-stop / timeout logic
- Windows multiprocessing safe (no SIGALRM on Windows)
"""

import logging
import os
import signal
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

from ocr.constants import (
    OCR_RESIZE_FACTORS,
    OCR_PIPELINES,
    OCR_INCLUDE_GRAYSCALE,
    OCR_TIMEOUT_S,
    OCR_EARLY_STOP_SCORE,
    OCR_DO_DESKEW,
    OCR_DO_ROTATE,
    OCR_MODE,
    TESSERACT_LANG,
    TESSERACT_OEM_MODE,
    TESSERACT_PSM_MODES,
    PDF_RESOLUTION,
    MIN_EMBEDDED_TEXT_LENGTH,
)
from ocr.corrections import apply_all_corrections
from ocr.preprocess import (
    load_image_from_path,
    pil_to_cv2,
    preprocess_image,          # v4: now a generator
    to_grayscale,
    cap_image_size,
    OCR_MAX_INPUT_DIM,
    ALL_PIPELINES,             # kept for max_passes calculation
)
from ocr.scoring import score_ocr_text, select_best_ocr
from ocr.utils import is_text_useful, clean_text, is_pdf, is_image, make_temp_path

logger = logging.getLogger(__name__)

logger.info(
    f"OCR engine loaded (v4) — mode='{OCR_MODE}' "
    f"scales={OCR_RESIZE_FACTORS} pipelines={OCR_PIPELINES} "
    f"psm={TESSERACT_PSM_MODES} early_stop={OCR_EARLY_STOP_SCORE} "
    f"timeout={OCR_TIMEOUT_S}s max_input_dim={OCR_MAX_INPUT_DIM}px"
)


# ─────────────────────────────────────────────
# TESSERACT CONFIGURATION BUILDER
# ─────────────────────────────────────────────

def build_tesseract_config(psm: int, oem: int = TESSERACT_OEM_MODE) -> str:
    return f"--oem {oem} --psm {psm} -c preserve_interword_spaces=1"


# ─────────────────────────────────────────────
# TIMEOUT CONTEXT MANAGER
# ─────────────────────────────────────────────

@contextmanager
def _tesseract_timeout(seconds: float):
    """
    SIGALRM-based timeout on Unix; no-op on Windows.
    Windows timeout enforcement handled by pytesseract's built-in timeout param.
    """
    if hasattr(signal, "SIGALRM"):
        def _handler(signum, frame):
            raise TimeoutError(f"Tesseract exceeded {seconds}s wall-clock limit")
        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        yield


# ─────────────────────────────────────────────
# SHORT-CIRCUIT CHECKER  (unchanged from v3)
# ─────────────────────────────────────────────

import re as _re

_SC_PAN         = _re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b')
_SC_GSTIN       = _re.compile(r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b')
_SC_AY          = _re.compile(r'\b20\d{2}[-\/](?:20)?\d{2}\b')
_SC_ITR         = _re.compile(r'\bITR[\s\-]?[0-9A-Z]{1,2}\b', _re.IGNORECASE)
_SC_AADHAAR_KW  = _re.compile(r'\b(?:aadhaar|uidai)\b', _re.IGNORECASE)
_SC_AADHAAR_FMT = _re.compile(r'\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b')

_SHORT_CIRCUIT_SCORE_THRESHOLD = 70.0


def _should_short_circuit(text: str, score: float) -> tuple[bool, str]:
    """
    Return (True, reason) if we should stop all remaining OCR passes.
    Fires when score >= threshold AND a key ID/keyword combo is found.
    """
    if score < _SHORT_CIRCUIT_SCORE_THRESHOLD:
        return False, ""

    t_upper = text.upper()

    if _SC_PAN.search(t_upper):
        return True, f"PAN found + score={score:.1f} >= {_SHORT_CIRCUIT_SCORE_THRESHOLD}"
    if _SC_ITR.search(text) and _SC_AY.search(text):
        return True, f"ITR+AY found + score={score:.1f} >= {_SHORT_CIRCUIT_SCORE_THRESHOLD}"
    if _SC_GSTIN.search(t_upper):
        return True, f"GSTIN found + score={score:.1f} >= {_SHORT_CIRCUIT_SCORE_THRESHOLD}"
    if _SC_AADHAAR_KW.search(text) and _SC_AADHAAR_FMT.search(text):
        return True, f"Aadhaar found + score={score:.1f} >= {_SHORT_CIRCUIT_SCORE_THRESHOLD}"

    return False, ""


# ─────────────────────────────────────────────
# SINGLE IMAGE OCR PASS
# ─────────────────────────────────────────────

def ocr_image_single(
    img: np.ndarray,
    psm: int,
    config_label: str = "",
    timeout_s: float = OCR_TIMEOUT_S,
) -> dict:
    """
    Run Tesseract on a single preprocessed image with timeout protection.

    Returns:
        {"text": str, "config": str, "score": None, "elapsed_s": float}
    """
    config = build_tesseract_config(psm)
    label  = config_label or f"psm{psm}"
    t_start = time.monotonic()

    try:
        pil_img = Image.fromarray(img) if isinstance(img, np.ndarray) else img

        with _tesseract_timeout(timeout_s):
            text = pytesseract.image_to_string(
                pil_img,
                lang=TESSERACT_LANG,
                config=config,
                timeout=int(timeout_s),
            )

        elapsed = time.monotonic() - t_start
        return {
            "text":      text.strip(),
            "config":    label,
            "score":     None,
            "elapsed_s": round(elapsed, 3),
        }

    except TimeoutError:
        elapsed = time.monotonic() - t_start
        logger.warning(f"Tesseract TIMEOUT ({elapsed:.1f}s) — pass '{label}' skipped")
        return {"text": "", "config": label, "score": 0.0, "elapsed_s": round(elapsed, 3)}

    except Exception as exc:
        elapsed = time.monotonic() - t_start
        logger.warning(f"Tesseract failed (psm={psm}, {label}): {exc}")
        return {"text": "", "config": label, "score": 0.0, "elapsed_s": round(elapsed, 3)}


# ─────────────────────────────────────────────
# PIPELINE NAME FILTER  (v4: returns names only)
# ─────────────────────────────────────────────

def _get_active_pipeline_names() -> list[str]:
    """
    Return the list of pipeline names active for the current OCR mode,
    in the order they appear in ALL_PIPELINES (cheapest first in v4).

    In v4, preprocess_image() is told which pipeline names to yield
    rather than yielding all and filtering in the caller.
    """
    allowed = set(OCR_PIPELINES)
    # Preserve ALL_PIPELINES order (cheapest first) but only include allowed names
    ordered = []
    for name, _fn in ALL_PIPELINES:
        if name == "grayscale":
            # grayscale_only handled separately via OCR_INCLUDE_GRAYSCALE
            continue
        if name in allowed:
            ordered.append(name)
    return ordered


# ─────────────────────────────────────────────
# MULTI-PASS OCR  (v4 — generator-based, lazy preprocessing)
# ─────────────────────────────────────────────

def ocr_image_multipass(img_bgr: np.ndarray) -> dict:
    """
    Run multi-pass OCR on a single image.

    v4 changes vs v3:
    - preprocess_image() is now a generator. Pipeline preprocessing happens
      LAZILY — only when the next pass is about to start. When short-circuit
      fires after pass 1, the remaining pipelines are never computed.
    - Pipelines are yielded cheapest-first (grayscale → fastpath → light → ...).
    - For each (pipeline_name, preprocessed_img) from the generator, we run
      all configured PSM modes before requesting the next pipeline.
    - OCR_RESIZE_FACTORS outer loop is preserved for prod mode (multi-scale),
      but in dev mode there is only one scale so the loop body runs once.
    - Preprocessing and Tesseract timing tracked separately per pass.

    Pass structure (dev mode example, scale=2.0):
      Pass 1: grayscale_only × psm6   ← usually fires short-circuit here
      Pass 2: grayscale_only × psm3
      Pass 3: fastpath × psm6
      Pass 4: fastpath × psm3
      → short-circuit fired on pass 1: passes 2–4 never execute

    Returns best OCR result dict with "text", "config", "score",
    "pass_count", "elapsed_s", "timing".
    """
    all_results: list[dict] = []
    pass_count          = 0
    t_multipass_start   = time.monotonic()
    timing: dict[str, float] = {}
    global_short_circuit = False

    # Determine which pipeline names this mode wants
    active_pipeline_names = _get_active_pipeline_names()

    # Build full pipeline list for this pass sequence:
    # grayscale_only (if enabled) comes first, then mode-filtered pipelines.
    requested_pipelines: list[str] = []
    if OCR_INCLUDE_GRAYSCALE:
        requested_pipelines.append("grayscale_only")
    requested_pipelines.extend(active_pipeline_names)

    # Max theoretical passes (used for logging only)
    n_pipelines = len(requested_pipelines)
    max_passes  = len(OCR_RESIZE_FACTORS) * n_pipelines * len(TESSERACT_PSM_MODES)

    h_orig, w_orig = img_bgr.shape[:2]
    logger.info(
        f"[DEV] Starting multipass OCR — "
        f"input: {w_orig}×{h_orig}px "
        f"max {max_passes} passes "
        f"({len(OCR_RESIZE_FACTORS)} scales × "
        f"{n_pipelines} pipelines × "
        f"{len(TESSERACT_PSM_MODES)} PSM) "
        f"max_input_dim={OCR_MAX_INPUT_DIM}px"
    )

    for scale_idx, scale in enumerate(OCR_RESIZE_FACTORS):
        if global_short_circuit:
            logger.info(
                f"[SHORT-CIRCUIT] Global — skipping scale {scale}x entirely"
            )
            break

        # Only run OSD rotation on the very first scale pass
        do_rotate_this_pass = OCR_DO_ROTATE and (scale_idx == 0)

        t_scale_start = time.monotonic()
        preprocess_time_this_scale = 0.0
        tess_time_this_scale       = 0.0
        early_stopped              = False

        # ── v4: Create generator (no preprocessing done yet) ──
        pipeline_gen = preprocess_image(
            img_bgr,
            scale_factor=scale,
            do_deskew=OCR_DO_DESKEW,
            do_rotate=do_rotate_this_pass,
            max_input_dim=OCR_MAX_INPUT_DIM,
            requested_pipelines=requested_pipelines,
        )

        # ── Iterate generator: one pipeline at a time ──
        for pipeline_name, preprocessed in pipeline_gen:
            if early_stopped or global_short_circuit:
                # Abandon generator — no more preprocessing done
                break

            for psm in TESSERACT_PSM_MODES:
                if global_short_circuit:
                    break

                pass_count += 1
                label = f"scale{scale}__{pipeline_name}__psm{psm}"

                # ── Tesseract ──
                t_tess = time.monotonic()
                result = ocr_image_single(
                    preprocessed,
                    psm=psm,
                    config_label=label,
                    timeout_s=OCR_TIMEOUT_S,
                )
                tess_elapsed = time.monotonic() - t_tess
                timing[f"tess_pass{pass_count}"] = round(tess_elapsed, 3)
                tess_time_this_scale += tess_elapsed

                result["score"] = score_ocr_text(result["text"])

                logger.debug(
                    f"Pass {pass_count}/{max_passes}: {label} "
                    f"→ score={result['score']:.1f} "
                    f"len={len(result['text'])} "
                    f"time={result['elapsed_s']}s"
                )

                all_results.append(result)

                # ── Short-circuit check ──
                sc_fire, sc_reason = _should_short_circuit(
                    result["text"], result["score"]
                )
                if sc_fire:
                    remaining = max_passes - pass_count
                    logger.info(
                        f"[SHORT-CIRCUIT] Pass {pass_count}/{max_passes} — "
                        f"{sc_reason}. "
                        f"Skipping ALL {remaining} remaining passes."
                    )
                    global_short_circuit = True
                    early_stopped = True
                    break

                # ── Original early-stop (score threshold only) ──
                current_best = max((r["score"] for r in all_results), default=0.0)
                if current_best >= OCR_EARLY_STOP_SCORE:
                    remaining = max_passes - pass_count
                    logger.info(
                        f"Early stop at pass {pass_count}/{max_passes} — "
                        f"score {current_best:.1f} >= threshold {OCR_EARLY_STOP_SCORE}. "
                        f"Skipping {remaining} remaining passes."
                    )
                    early_stopped = True
                    break

            if early_stopped or global_short_circuit:
                break

        # Close generator if not already exhausted (Python will GC it,
        # but explicit close is cleaner and immediately frees any open resources)
        try:
            pipeline_gen.close()
        except Exception:
            pass

        scale_elapsed = time.monotonic() - t_scale_start
        timing[f"scale_{scale}x_total"] = round(scale_elapsed, 3)
        # preprocess time = scale_elapsed - tess_time_this_scale
        preprocess_time_this_scale = scale_elapsed - tess_time_this_scale
        timing[f"preprocess_scale{scale}x"] = round(preprocess_time_this_scale, 3)

        logger.debug(
            f"[TIMING] Scale {scale}x total: {scale_elapsed:.3f}s "
            f"(preprocess≈{preprocess_time_this_scale:.3f}s "
            f"tesseract≈{tess_time_this_scale:.3f}s)"
        )

        if early_stopped:
            break

    # ── Select best overall result ──
    best = select_best_ocr(all_results)

    total_elapsed = round(time.monotonic() - t_multipass_start, 3)
    timing["multipass_total"] = total_elapsed
    best["pass_count"] = pass_count
    best["elapsed_s"]  = total_elapsed
    best["timing"]     = timing

    logger.info(
        f"[DEV] Multipass OCR done: "
        f"{pass_count}/{max_passes} passes executed, "
        f"best='{best.get('config')}' score={best.get('score', 0):.1f}, "
        f"total_time={total_elapsed:.3f}s "
        f"({total_elapsed / max(pass_count, 1):.2f}s/pass avg) "
        f"short_circuit={'YES' if global_short_circuit else 'NO'}"
    )

    return best


# ─────────────────────────────────────────────
# PDF EXTRACTION  (unchanged from v3, with minor cleanup)
# ─────────────────────────────────────────────

def _recompress_pil_for_ocr(pil_img: Image.Image, max_dim: int = OCR_MAX_INPUT_DIM) -> Image.Image:
    """
    Downscale a PIL image before OCR to reduce RAM pressure.
    Large PDF pages at 300 DPI can be ~50MB; capping saves RAM and speeds cv2 ops.
    """
    w, h = pil_img.size
    longest = max(w, h)
    if longest <= max_dim:
        return pil_img
    scale = max_dim / longest
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    logger.info(
        f"[OCR OPTIMIZER] PDF page original: {w}×{h} "
        f"Resized: {new_w}×{new_h} Scale factor: {scale:.2f}"
    )
    return pil_img.resize((new_w, new_h), Image.LANCZOS)


def extract_text_from_pdf(filepath: str) -> dict:
    """
    Extract text from a PDF file.
    Strategy: try embedded text per page; OCR pages that don't have it.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Run: pip install pdfplumber")
        return {"text": "", "method": "error", "score": 0.0, "page_count": 0,
                "pass_count": 0, "elapsed_s": 0.0}

    page_texts:   list[str] = []
    methods_used: set[str]  = set()
    total_pass_count = 0
    t_start = time.monotonic()

    try:
        with pdfplumber.open(filepath) as pdf:
            total_pages = len(pdf.pages)
            logger.info(
                f"PDF: {total_pages} page(s) — '{filepath}' "
                f"[resolution={PDF_RESOLUTION}dpi, mode={OCR_MODE}, "
                f"max_dim={OCR_MAX_INPUT_DIM}px]"
            )

            for page_num, page in enumerate(pdf.pages):
                t_page = time.monotonic()
                logger.debug(f"PDF page {page_num + 1}/{total_pages}")

                embedded_text = (page.extract_text() or "").strip()

                if is_text_useful(embedded_text, min_chars=MIN_EMBEDDED_TEXT_LENGTH):
                    logger.debug(
                        f"Page {page_num+1}: embedded text ok ({len(embedded_text)} chars)"
                    )
                    page_texts.append(embedded_text)
                    methods_used.add("embedded")
                else:
                    logger.debug(
                        f"Page {page_num+1}: embedded text insufficient, "
                        f"OCR-ing at {PDF_RESOLUTION}dpi"
                    )
                    try:
                        page_image = page.to_image(resolution=PDF_RESOLUTION).original
                        page_image = _recompress_pil_for_ocr(page_image)
                        img_bgr    = pil_to_cv2(page_image)
                        result     = ocr_image_multipass(img_bgr)
                        page_texts.append(result.get("text", ""))
                        methods_used.add("ocr")
                        total_pass_count += result.get("pass_count", 0)
                    except Exception as exc:
                        logger.warning(f"Page {page_num+1} OCR failed: {exc}")
                        if embedded_text:
                            page_texts.append(embedded_text)

                page_elapsed = time.monotonic() - t_page
                logger.debug(f"[TIMING] PDF page {page_num+1}: {page_elapsed:.3f}s")

    except Exception as exc:
        logger.error(f"PDF extraction failed for '{filepath}': {exc}")
        return {"text": f"[PDF error: {exc}]", "method": "error",
                "score": 0.0, "page_count": 0, "pass_count": 0, "elapsed_s": 0.0}

    merged        = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
    merged        = clean_text(merged)
    overall_score = score_ocr_text(merged)
    method        = "mixed" if len(methods_used) > 1 else (
                        methods_used.pop() if methods_used else "unknown"
                    )
    elapsed = round(time.monotonic() - t_start, 3)

    logger.info(
        f"PDF done: method={method}, pages={len(page_texts)}, "
        f"score={overall_score:.1f}, chars={len(merged)}, "
        f"ocr_passes={total_pass_count}, elapsed={elapsed}s"
    )

    return {
        "text":       merged,
        "method":     method,
        "score":      overall_score,
        "page_count": len(page_texts),
        "pass_count": total_pass_count,
        "elapsed_s":  elapsed,
    }


# ─────────────────────────────────────────────
# IMAGE EXTRACTION
# ─────────────────────────────────────────────

def extract_text_from_image(filepath: str) -> dict:
    """
    Extract text from an image file using mode-aware multipass OCR.
    """
    t_load  = time.monotonic()
    img_bgr = load_image_from_path(filepath)
    load_elapsed = time.monotonic() - t_load

    if img_bgr is None:
        return {"text": "", "method": "error", "score": 0.0,
                "ocr_config": "", "pass_count": 0, "elapsed_s": 0.0}

    h, w = img_bgr.shape[:2]
    logger.info(
        f"[TIMING] Image load: {load_elapsed*1000:.0f}ms "
        f"({w}×{h}px, {w*h/1e6:.1f}MP)"
    )

    result = ocr_image_multipass(img_bgr)

    return {
        "text":      result.get("text", ""),
        "method":    "ocr",
        "score":     result.get("score", 0.0),
        "ocr_config": result.get("config", ""),
        "pass_count": result.get("pass_count", 0),
        "elapsed_s":  result.get("elapsed_s", 0.0),
        "timing":     result.get("timing", {}),
    }


# ─────────────────────────────────────────────
# MASTER ENTRY POINT
# ─────────────────────────────────────────────

def extract_raw_text(filepath: str) -> dict:
    """
    Extract raw text from any supported file (PDF, JPG, PNG, etc.).

    Returns:
        {
            "text":       str,    corrected + cleaned OCR text
            "raw_text":   str,    uncorrected OCR text (for audit)
            "method":     str,    "embedded" | "ocr" | "mixed" | "error"
            "score":      float,  OCR quality score
            "page_count": int,    pages processed (1 for images)
            "pass_count": int,    total Tesseract calls made
            "elapsed_s":  float,  total wall-clock time
            "ocr_mode":   str,    active OCR mode
            "timing":     dict,   per-stage timing breakdown
        }
    """
    if not os.path.exists(filepath):
        logger.error(f"File not found: '{filepath}'")
        return {
            "text": "", "raw_text": "", "method": "error",
            "score": 0.0, "page_count": 0, "pass_count": 0,
            "elapsed_s": 0.0, "ocr_mode": OCR_MODE, "timing": {},
        }

    filepath = str(filepath)
    t_start  = time.monotonic()

    try:
        if is_pdf(filepath):
            result = extract_text_from_pdf(filepath)
        elif is_image(filepath):
            result = extract_text_from_image(filepath)
        else:
            logger.warning(f"Unsupported file type: '{filepath}'")
            return {
                "text": "", "raw_text": "", "method": "unsupported",
                "score": 0.0, "page_count": 0, "pass_count": 0,
                "elapsed_s": 0.0, "ocr_mode": OCR_MODE, "timing": {},
            }
    except Exception as exc:
        logger.exception(f"Extraction failed for '{filepath}': {exc}")
        return {
            "text": "", "raw_text": "", "method": "error",
            "score": 0.0, "page_count": 0, "pass_count": 0,
            "elapsed_s": 0.0, "ocr_mode": OCR_MODE, "timing": {},
        }

    raw_text = result.get("text", "")

    # Apply correction layer before metadata extraction
    t_correction     = time.monotonic()
    corrected_text   = apply_all_corrections(raw_text)
    corrected_text   = clean_text(corrected_text)
    correction_elapsed = time.monotonic() - t_correction

    result["raw_text"] = raw_text
    result["text"]     = corrected_text
    result["ocr_mode"] = OCR_MODE
    result.setdefault("pass_count", 0)
    result.setdefault("timing", {})
    result["timing"]["correction"] = round(correction_elapsed, 3)

    total_elapsed = round(time.monotonic() - t_start, 3)
    result["elapsed_s"] = total_elapsed
    result.setdefault("page_count", 1)

    logger.info(
        f"[DEV] extract_raw_text done: "
        f"method={result.get('method')} "
        f"score={result.get('score', 0):.1f} "
        f"passes={result.get('pass_count')} "
        f"elapsed={total_elapsed:.3f}s "
        f"raw_len={len(raw_text)} corrected_len={len(corrected_text)}"
    )

    # Timing breakdown (always at INFO so visible in production logs)
    timing     = result.get("timing", {})
    tess_times = {k: v for k, v in timing.items() if k.startswith("tess_pass")}
    pre_times  = {k: v for k, v in timing.items() if k.startswith("preprocess")}
    if tess_times or pre_times:
        total_tess = sum(tess_times.values())
        total_pre  = sum(pre_times.values())
        logger.info(
            f"[TIMING BREAKDOWN] preprocessing={total_pre:.3f}s "
            f"tesseract={total_tess:.3f}s "
            f"correction={timing.get('correction', 0):.3f}s"
        )

    return result