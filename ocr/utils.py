"""
DocuFlow AI - Shared Utility Functions
"""

import os
import re
import logging
import tempfile
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# FILE UTILITIES
# ─────────────────────────────────────────────

def get_file_extension(filepath: str) -> str:
    """Return lowercase file extension including dot."""
    return Path(filepath).suffix.lower()


def is_pdf(filepath: str) -> bool:
    return get_file_extension(filepath) == ".pdf"


def is_image(filepath: str) -> bool:
    return get_file_extension(filepath) in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")


def make_temp_path(suffix: str = ".png") -> str:
    """Create a temporary file path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


# ─────────────────────────────────────────────
# TEXT QUALITY UTILITIES
# ─────────────────────────────────────────────

def text_quality_score(text: str) -> float:
    """
    Quick quality signal for extracted text.
    Returns 0-1 score based on:
    - Ratio of printable ASCII characters
    - Ratio of alphanumeric characters
    - Word count
    """
    if not text or len(text) < 5:
        return 0.0

    total = len(text)
    printable = sum(1 for c in text if c.isprintable() or c in "\n\t")
    alnum = sum(1 for c in text if c.isalnum())
    words = len(text.split())

    printable_ratio = printable / total
    alnum_ratio = alnum / total
    word_score = min(words / 50.0, 1.0)  # saturates at 50 words

    return (printable_ratio * 0.4 + alnum_ratio * 0.3 + word_score * 0.3)


def is_text_useful(text: str, min_chars: int = 40) -> bool:
    """Check if extracted text is likely real content vs. garbage."""
    if not text or len(text.strip()) < min_chars:
        return False
    score = text_quality_score(text)
    return score >= 0.3


def clean_text(text: str) -> str:
    """
    Normalize whitespace and remove control characters from text.
    Preserves newlines for layout.
    """
    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)
    # Remove control chars except newline/tab
    text = re.sub(r'[^\x09\x0A\x20-\x7E\u0900-\u097F]', ' ', text)
    # Collapse horizontal whitespace (but keep newlines)
    text = re.sub(r'[ \t]+', ' ', text)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace to single spaces."""
    return ' '.join(text.split())


# ─────────────────────────────────────────────
# STRING MATCHING UTILITIES
# ─────────────────────────────────────────────

def contains_keyword(text: str, keyword: str) -> bool:
    """Case-insensitive keyword check."""
    return keyword.lower() in text.lower()


def keyword_score(text: str, keywords: list[tuple[str, int]]) -> int:
    """
    Score text by checking for keywords with associated weights.
    Returns total score.
    """
    text_lower = text.lower()
    total = 0
    for kw, weight in keywords:
        if kw.lower() in text_lower:
            total += weight
    return total


def extract_lines(text: str) -> list[str]:
    """Split text into non-empty lines, stripped."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_words(text: str) -> list[str]:
    """Split text into words (alphanumeric sequences)."""
    return re.findall(r'\b\w+\b', text)


def get_context_window(text: str, position: int, window: int = 100) -> str:
    """
    Return a window of text around a position.
    Useful for context-aware extraction.
    """
    start = max(0, position - window)
    end = min(len(text), position + window)
    return text[start:end]


# ─────────────────────────────────────────────
# NAME UTILITIES
# ─────────────────────────────────────────────

def is_likely_name(token: str, blacklist: set) -> bool:
    """
    Heuristic: is this token likely a person/company name?
    - Must have 2+ alphabetic chars
    - Must not be in blacklist
    - Must not be all digits
    - Must not be too short (< 2 chars) or too long (> 60 chars)
    """
    token = token.strip()
    if len(token) < 2 or len(token) > 60:
        return False
    if token.lower() in blacklist:
        return False
    if re.fullmatch(r'\d+', token):
        return False
    alpha_count = sum(1 for c in token if c.isalpha())
    if alpha_count < 2:
        return False
    return True


def normalize_name(name: str) -> str:
    """
    Normalize a detected name:
    - Strip leading/trailing whitespace
    - Collapse internal whitespace
    - Title-case
    - Remove non-alpha except spaces and hyphens
    """
    name = re.sub(r'[^a-zA-Z\s\-\.]', '', name)
    name = ' '.join(name.split())
    name = name.title()
    return name.strip()


# ─────────────────────────────────────────────
# NUMBER UTILITIES
# ─────────────────────────────────────────────

def extract_digits(text: str) -> str:
    """Return only digit characters from text."""
    return re.sub(r'\D', '', text)


def is_numeric_heavy(text: str, threshold: float = 0.4) -> bool:
    """Check if text is dominated by numbers (e.g., table data)."""
    if not text:
        return False
    digits = sum(1 for c in text if c.isdigit())
    return digits / len(text) >= threshold


# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────

def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the OCR pipeline."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def log_ocr_attempt(pass_num: int, config: dict, score: float, text_preview: str) -> None:
    """Log details of a single OCR pass."""
    preview = text_preview[:80].replace('\n', ' ') if text_preview else ""
    logger.debug(
        f"OCR Pass {pass_num} | config={config} | score={score:.2f} | preview='{preview}'"
    )
