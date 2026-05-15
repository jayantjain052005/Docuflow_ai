"""
DocuFlow AI - Groq AI Service
"""

import json
import re
import os

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Initialize Groq client
client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


def extract_metadata(text: str) -> dict:
    """
    Analyze OCR text and return structured metadata.
    """

    default = {
        "document_type": "Unknown",
        "year": "",
        "important_ids": [],
        "summary": "AI temporarily unavailable.",
    }

    # Empty text check
    if not text or len(text.strip()) < 20:
        default["summary"] = "Document unreadable."
        return default

    # Clean text
    text = text.strip()

    # Regex extraction
    aadhaar = re.findall(r"\b\d{4}\s\d{4}\s\d{4}\b", text)

    pan = re.findall(
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        text
    )

    years = re.findall(r"\b20\d{2}\b", text)

    lower_text = text.lower()

    # -----------------------------------------
    # RULE-BASED CLASSIFICATION
    # -----------------------------------------

    # Enrollment Slip Detection
    if "enrollment" in lower_text:
        return {
            "document_type": "Enrollment Certificate",
            "year": years[0] if years else "",
            "important_ids": aadhaar,
            "summary": text[:200]
        }

    # Aadhaar Detection
    if (
        "aadhaar" in lower_text
        or "uidai" in lower_text
        or aadhaar
    ):
        return {
            "document_type": "Aadhaar Card",
            "year": years[0] if years else "",
            "important_ids": aadhaar,
            "summary": text[:200]
        }

    # PAN Detection
    if pan:
        return {
            "document_type": "PAN Card",
            "year": years[0] if years else "",
            "important_ids": pan,
            "summary": text[:200]
        }

    # -----------------------------------------
    # AI FALLBACK
    # -----------------------------------------

    text_sample = text[:1500]

    prompt = f"""
You are an Indian document classification AI.

Analyze the OCR text carefully.

Possible document types:
- Aadhaar Card
- PAN Card
- Passport
- Driving License
- Bank Statement
- Marksheet
- Enrollment Certificate
- Invoice
- Insurance
- Other

Important rules:
- Aadhaar cards contain UIDAI or 12 digit number.
- PAN cards contain PAN format like ABCDE1234F.
- Enrollment slips are different from Aadhaar cards.
- Return ONLY valid JSON.
- No markdown.
- No explanation.

Document text:
{text_sample}

Return JSON format:

{{
  "document_type": "",
  "year": "",
  "important_ids": [],
  "summary": ""
}}
"""

    try:

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2
        )

        raw = response.choices[0].message.content.strip()

        # Remove markdown formatting
        raw = re.sub(
            r"^```json",
            "",
            raw,
            flags=re.IGNORECASE
        ).strip()

        raw = re.sub(r"^```", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()

        parsed = json.loads(raw)

        important_ids = parsed.get(
            "important_ids",
            []
        )

        # Add regex extracted IDs
        important_ids.extend(aadhaar)
        important_ids.extend(pan)

        # Remove duplicates
        important_ids = list(set(important_ids))

        return {
            "document_type": parsed.get(
                "document_type",
                "Unknown"
            ),

            "year": parsed.get(
                "year",
                years[0] if years else ""
            ),

            "important_ids": important_ids,

            "summary": parsed.get(
                "summary",
                text[:200]
            ),
        }

    except json.JSONDecodeError:

        default["summary"] = (
            "AI response parsing failed."
        )

        return default

    except Exception as e:

        print("Groq Error:", e)

        return default


def understand_search_query(query: str) -> str:
    """
    Convert natural language search into keywords.
    """

    if not query:
        return query

    prompt = f"""
Convert this search query into simple search keywords.

Query:
{query}

Return ONLY keywords.
"""

    try:

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        keywords = (
            response
            .choices[0]
            .message
            .content
            .strip()
            .lower()
        )

        keywords = re.sub(
            r"[^\w\s]",
            " ",
            keywords
        )

        return keywords.strip()

    except Exception as e:

        print("Search Error:", e)

        return query