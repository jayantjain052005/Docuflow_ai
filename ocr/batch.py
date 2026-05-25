"""
DocuFlow AI - Batch OCR Processor  (production-grade)

Features:
- Multiprocessing batch OCR (configurable worker count)
- File-based OCR result cache (JSON, keyed by SHA-256 hash)
- Per-file timing metrics
- Structured logging per batch
- Graceful error handling (one failed file never kills the batch)
- Integration with routing.py for full pipeline runs

Usage:
    from ocr.batch import BatchProcessor

    processor = BatchProcessor(
        workers=4,
        cache_dir="/tmp/docuflow_cache",
        client_registry=[...],   # optional, for routing
    )
    results = processor.process_batch(["/path/to/file1.pdf", ...])
    for r in results:
        print(r["action"], r["file"])
"""

import hashlib
import json
import logging
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# OCR RESULT CACHE
# ─────────────────────────────────────────────

class OCRCache:
    """
    Simple file-based JSON cache for OCR results.

    Cache key: SHA-256 hash of the file bytes.
    Cache value: the full dict returned by process_document().

    Storing by content hash means that re-uploading the same scan
    (same bytes, different filename) hits the cache — no redundant OCR.
    """

    def __init__(self, cache_dir: str = "/tmp/docuflow_ocr_cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0
        logger.info(f"OCR cache initialized at '{self.cache_dir}'")

    def _cache_path(self, file_hash: str) -> Path:
        return self.cache_dir / f"{file_hash}.json"

    def _hash_file(self, filepath: str) -> Optional[str]:
        try:
            sha = hashlib.sha256()
            with open(filepath, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    sha.update(chunk)
            return sha.hexdigest()
        except (OSError, IOError) as exc:
            logger.warning(f"Cannot hash '{filepath}': {exc}")
            return None

    def get(self, filepath: str) -> Optional[dict]:
        """Return cached OCR result for this file, or None on cache miss."""
        file_hash = self._hash_file(filepath)
        if not file_hash:
            return None
        path = self._cache_path(file_hash)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    result = json.load(fh)
                self._hits += 1
                logger.debug(f"Cache HIT: '{Path(filepath).name}' (hash={file_hash[:12]}...)")
                return result
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"Cache read error for '{filepath}': {exc}")
        self._misses += 1
        return None

    def set(self, filepath: str, result: dict) -> None:
        """Store OCR result in cache."""
        file_hash = self._hash_file(filepath)
        if not file_hash:
            return
        path = self._cache_path(file_hash)
        try:
            # Exclude non-serialisable debug fields
            serialisable = {k: v for k, v in result.items() if k != "_debug"}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(serialisable, fh, ensure_ascii=False, indent=2)
            logger.debug(f"Cache SET: '{Path(filepath).name}' (hash={file_hash[:12]}...)")
        except (OSError, TypeError) as exc:
            logger.warning(f"Cache write error for '{filepath}': {exc}")

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = self._hits / total * 100 if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate_pct": round(hit_rate, 1),
        }


# ─────────────────────────────────────────────
# SINGLE-FILE WORKER (top-level for pickling)
# ─────────────────────────────────────────────

def _process_single_file(args: tuple) -> dict:
    """
    Top-level function for multiprocessing workers.

    Must be a module-level function (not a lambda or closure) so that
    Python's `multiprocessing` can pickle it.

    Returns a result dict that always has "file" and "status" keys,
    even on failure — so one bad file never kills the whole batch.
    """
    filepath, verbose = args
    t_start = time.monotonic()
    result = {
        "file": str(filepath),
        "status": "error",
        "elapsed_s": 0.0,
        "error": None,
    }
    try:
        # Import here so each worker gets a clean module state
        from ocr import process_document  # type: ignore
        ocr_result = process_document(str(filepath), verbose=verbose)
        elapsed = time.monotonic() - t_start
        result.update(ocr_result)
        result["status"] = "ok"
        result["elapsed_s"] = round(elapsed, 3)
    except Exception as exc:
        elapsed = time.monotonic() - t_start
        result["error"] = str(exc)
        result["elapsed_s"] = round(elapsed, 3)
        logger.error(f"Worker error on '{filepath}': {exc}", exc_info=True)
    return result


# ─────────────────────────────────────────────
# BATCH PROCESSOR
# ─────────────────────────────────────────────

class BatchProcessor:
    """
    Multiprocessing batch OCR processor with caching and routing.

    Args:
        workers:          Number of parallel OCR workers (default: CPU count).
        cache_dir:        Directory for OCR result cache (None = no cache).
        client_registry:  Optional client list for routing (see routing.py).
        verbose:          Enable debug logging in workers.
    """

    def __init__(
        self,
        workers: Optional[int] = None,
        cache_dir: Optional[str] = "/tmp/docuflow_ocr_cache",
        client_registry: Optional[list[dict]] = None,
        verbose: bool = False,
    ) -> None:
        self.workers = workers or max(1, mp.cpu_count() - 1)
        self.client_registry = client_registry or []
        self.verbose = verbose
        self.cache = OCRCache(cache_dir) if cache_dir else None
        logger.info(
            f"BatchProcessor ready: workers={self.workers} "
            f"cache={'enabled' if self.cache else 'disabled'}"
        )

    def process_batch(
        self,
        filepaths: list[str],
        use_routing: bool = True,
    ) -> list[dict]:
        """
        Process a batch of files using multiprocessing.

        Args:
            filepaths:    List of file paths to process.
            use_routing:  If True, appends routing decision to each result.

        Returns:
            List of result dicts, one per input file.
            Each dict has all fields from process_document() plus:
            - "status":    "ok" | "cached" | "error"
            - "elapsed_s": float (wall-clock time for this file)
            - "routing":   dict (only if use_routing=True)
        """
        if not filepaths:
            return []

        t_batch_start = time.monotonic()
        results = []
        to_process: list[str] = []

        # ── Cache lookup pass ──
        cached_results: dict[str, dict] = {}
        if self.cache:
            for fp in filepaths:
                cached = self.cache.get(fp)
                if cached is not None:
                    cached["status"] = "cached"
                    cached["elapsed_s"] = 0.0
                    cached["file"] = str(fp)
                    cached_results[str(fp)] = cached
                else:
                    to_process.append(fp)
        else:
            to_process = list(filepaths)

        logger.info(
            f"Batch: {len(filepaths)} files total — "
            f"{len(cached_results)} cached, {len(to_process)} to OCR"
        )

        # ── Multiprocessing OCR pass ──
        worker_args = [(fp, self.verbose) for fp in to_process]
        fresh_results: list[dict] = []

        if to_process:
            if self.workers > 1 and len(to_process) > 1:
                with mp.Pool(processes=self.workers) as pool:
                    fresh_results = pool.map(_process_single_file, worker_args)
            else:
                # Single-threaded fallback (easier to debug)
                fresh_results = [_process_single_file(a) for a in worker_args]

            # Store successful results in cache
            if self.cache:
                for r in fresh_results:
                    if r.get("status") == "ok":
                        self.cache.set(r["file"], r)

        # ── Merge results in original order ──
        ocr_by_file = {r["file"]: r for r in fresh_results}
        for fp in filepaths:
            fp_str = str(fp)
            if fp_str in cached_results:
                results.append(cached_results[fp_str])
            elif fp_str in ocr_by_file:
                results.append(ocr_by_file[fp_str])
            else:
                results.append({"file": fp_str, "status": "missing", "elapsed_s": 0.0})

        # ── Routing pass ──
        if use_routing and self.client_registry is not None:
            from ocr.routing import build_routing_decision, DuplicateDetector
            detector = DuplicateDetector()
            for r in results:
                if r.get("status") in ("ok", "cached"):
                    try:
                        routing = build_routing_decision(
                            r["file"],
                            r,
                            client_registry=self.client_registry,
                            duplicate_detector=detector,
                        )
                        r["routing"] = routing
                        r["action"] = routing["action"]
                        r["action_reason"] = routing["action_reason"]
                    except Exception as exc:
                        logger.warning(
                            f"Routing failed for '{r['file']}': {exc}"
                        )
                        r["routing"] = None
                        r["action"] = "review"
                        r["action_reason"] = f"Routing error: {exc}"

        # ── Batch summary ──
        t_elapsed = time.monotonic() - t_batch_start
        self._log_batch_summary(results, t_elapsed)

        return results

    @staticmethod
    def _log_batch_summary(results: list[dict], elapsed_s: float) -> None:
        total = len(results)
        ok = sum(1 for r in results if r.get("status") == "ok")
        cached = sum(1 for r in results if r.get("status") == "cached")
        errors = sum(1 for r in results if r.get("status") == "error")
        review = sum(1 for r in results if r.get("action") == "review")
        skipped = sum(1 for r in results if r.get("action") == "skip")
        uploaded = sum(1 for r in results if r.get("action") == "upload")

        avg_time = elapsed_s / max(total, 1)
        logger.info(
            f"Batch complete: {total} files in {elapsed_s:.1f}s "
            f"({avg_time:.2f}s/file) | "
            f"OCR: {ok} ok / {cached} cached / {errors} errors | "
            f"Routing: {uploaded} upload / {review} review / {skipped} skip"
        )
