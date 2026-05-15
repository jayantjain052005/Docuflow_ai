# DocuFlow AI 🗂️

An AI-powered secure document vault built with Flask, SQLite, and Gemini API. Upload personal or client documents (PDF, JPG, PNG), and retrieve them later using natural language queries like *"2023 ITR"* or *"last year insurance policy"*.

---

## Features

- **User Authentication** — Register/Login with hashed passwords and Flask sessions
- **Document Upload** — Supports PDF, JPG, PNG with per-user isolated storage
- **OCR Processing** — Extracts text from images (pytesseract) and PDFs (pdfplumber)
- **Gemini AI Analysis** — Detects document type, year, key IDs, and summary
- **Natural Language Search** — Search metadata or let Gemini interpret your query
- **Dashboard** — View all documents with type, date, and download links
- **Security** — File validation, upload size limits, path traversal prevention

---

## Project Structure

```
docuflow_ai/
├── app.py                  # App entry point
├── config.py               # Configuration settings
├── database.py             # DB init and helpers
├── requirements.txt
├── .env.example
├── README.md
│
├── app/
│   ├── __init__.py         # Flask app factory
│   ├── models/
│   │   └── db_schema.sql   # SQL schema for users & documents
│   ├── routes/
│   │   ├── auth.py         # /register, /login, /logout
│   │   ├── documents.py    # /upload, /dashboard, /download, /delete
│   │   └── search.py       # /search
│   ├── services/
│   │   ├── gemini_service.py   # extract_metadata(), understand_search_query()
│   │   └── ocr_service.py      # extract_text_from_file()
│   ├── utils/
│   │   └── file_utils.py       # secure_filename, allowed extensions
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── register.html
│       ├── dashboard.html
│       ├── upload.html
│       └── search.html
│
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── main.js
│
└── uploads/                # Auto-created — stores user files
    └── <user_id>/
        └── document.pdf
```

---

## Prerequisites

- Python 3.9 or higher
- pip
- Tesseract OCR (for image text extraction)
- A Google Gemini API key

---

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourname/docuflow-ai.git
cd docuflow-ai
```

### 2. Create and Activate a Virtual Environment

```bash
# Create
python -m venv venv

# Activate (Linux/macOS)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Tesseract OCR

Tesseract is required for extracting text from image files (JPG, PNG).

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install tesseract-ocr -y
```

**macOS (Homebrew):**
```bash
brew install tesseract
```

**Windows:**
- Download the installer from: https://github.com/UB-Mannheim/tesseract/wiki
- Install it (default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
- Add that path to your system `PATH`, **or** set it in `config.py`:

```python
# config.py
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

**Verify Tesseract installation:**
```bash
tesseract --version
```

### 5. Set Up Your Gemini API Key

#### Get your key:
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the key

#### Configure it:
```bash
cp .env.example .env
```

Open `.env` and paste your key:
```
GEMINI_API_KEY=your_actual_api_key_here
SECRET_KEY=any_long_random_string_here
```

> **Note:** Never commit your `.env` file to Git. It is already in `.gitignore`.

### 6. Initialize the Database

```bash
python database.py
```

This creates `docuflow.db` with the `users` and `documents` tables.

### 7. Run the Application

```bash
python app.py
```

Open your browser and go to: **http://127.0.0.1:5000**

---

## Usage Guide

### Register & Login
- Visit `/register` to create an account
- Visit `/login` to sign in

### Upload a Document
- Go to `/upload`
- Select a PDF, JPG, or PNG file
- The app will:
  1. Save the file to `uploads/<your_user_id>/`
  2. Extract text using OCR or PDF parser
  3. Send text to Gemini API for analysis
  4. Store metadata (type, year, summary) in the database

### Search Documents
- Go to `/search`
- Type natural language queries like:
  - `aadhaar`
  - `2023 itr`
  - `insurance policy`
  - `last year tax`
- Results show matched documents with download links

### Dashboard
- Go to `/dashboard`
- View all your uploaded documents
- See detected type, upload date, year
- Download or delete any document

---

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `GEMINI_API_KEY` | Your Google Gemini API key | Yes |
| `SECRET_KEY` | Flask session secret key | Yes |
| `MAX_UPLOAD_MB` | Max file upload size in MB (default: 16) | No |
| `UPLOAD_FOLDER` | Path to uploads directory (default: `uploads/`) | No |

---

## Database Schema

### `users` table
| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| username | TEXT | Unique username |
| email | TEXT | Unique email address |
| password_hash | TEXT | Bcrypt/werkzeug hashed password |
| created_at | DATETIME | Account creation timestamp |

### `documents` table
| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| user_id | INTEGER | Foreign key → users.id |
| filename | TEXT | Original file name |
| filepath | TEXT | Relative path to stored file |
| document_type | TEXT | Gemini-detected type (e.g., "Aadhaar Card") |
| extracted_text | TEXT | Full OCR/parsed text |
| summary | TEXT | Gemini-generated summary |
| detected_year | TEXT | Year extracted from document |
| upload_date | DATETIME | When it was uploaded |

---

## Gemini API — What It Does

The Gemini API is called after OCR extracts raw text. It returns structured JSON:

```json
{
  "document_type": "Income Tax Return",
  "year": "2023",
  "important_ids": ["PAN: ABCDE1234F"],
  "summary": "ITR filed for FY 2022-23 with total income of ₹6,40,000"
}
```

**Functions in `services/gemini_service.py`:**

| Function | Purpose |
|---|---|
| `extract_metadata(text)` | Analyzes document text and returns structured info |
| `understand_search_query(query)` | Interprets vague search queries into keywords |

---

## Security Notes

- Passwords are hashed using `werkzeug.security` (PBKDF2 + SHA256)
- File extensions are validated against an allowlist (`pdf`, `jpg`, `jpeg`, `png`)
- Upload size is capped (default 16MB)
- `werkzeug.utils.secure_filename` prevents path traversal attacks
- Users can only access files that belong to their own `user_id`
- Session-based authentication required for all document routes

---

## Common Issues

**`tesseract is not installed or it's not in your PATH`**
→ Install Tesseract using the instructions in Step 4 above

**`GEMINI_API_KEY not set`**
→ Make sure your `.env` file exists and has the correct key

**`ModuleNotFoundError: No module named 'pdfplumber'`**
→ Run `pip install -r requirements.txt` again inside your virtual environment

**Upload fails silently**
→ Check that the `uploads/` folder exists, or run `python database.py` once

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask (Python) |
| Database | SQLite (via sqlite3) |
| Frontend | HTML + Bootstrap 5 |
| AI | Google Gemini API (`gemini-1.5-flash`) |
| OCR | pytesseract + Pillow |
| PDF Parsing | pdfplumber |
| Auth | Flask sessions + werkzeug |
| File Storage | Local filesystem |

---

## License

MIT License — free to use, modify, and distribute.

---

## Contributing

Pull requests welcome. For major changes, please open an issue first to discuss what you'd like to change.
