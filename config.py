"""
DocLedger CA Edition - Configuration
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import pytesseract


# Tesseract Path
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# Base Directory
BASE_DIR = Path(__file__).resolve().parent


# Load .env
load_dotenv(BASE_DIR / ".env")


class Config:

    # Flask
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "super-secret-key"
    )

    DEBUG = os.getenv(
        "FLASK_DEBUG",
        "1"
    ) == "1"

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///docledger_ca.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {
            "timeout": 30
        }
    }

    # JWT
    JWT_SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY",
        "jwt-secret-key"
    )

    # Uploads
    MAX_CONTENT_LENGTH = (
        int(os.getenv("MAX_UPLOAD_MB", 16))
        * 1024
        * 1024
    )

    UPLOAD_FOLDER = BASE_DIR / "uploads"

    ALLOWED_EXTENSIONS = {
        "pdf",
        "jpg",
        "jpeg",
        "png"
    }

    # Gemini / AI
    GEMINI_API_KEY = os.getenv(
        "GEMINI_API_KEY",
        ""
    )
