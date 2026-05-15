import re

from app.models.firm import Firm


YEAR_PATTERN = re.compile(
    r"(?:\bay\b|\bassessment\s+year\b)?\s*"
    r"\b(?:(20)?(\d{2})\s*[-/]\s*(20)?(\d{2}))\b",
    re.IGNORECASE,
)


def normalize_assessment_year(value):
    text = (value or "").strip()
    if not text:
        return None

    match = YEAR_PATTERN.search(text)
    if not match:
        return None

    start_prefix, start_year, end_prefix, end_year = match.groups()
    start_full = int(f"{start_prefix or '20'}{start_year}")
    end_full = int(f"{end_prefix or '20'}{end_year}")

    if end_full < start_full:
        end_full += 100

    return f"{start_full}-{str(end_full)[-2:]}"


# ---------------------------------------------------------
# Normalize document type into folder names
# ---------------------------------------------------------

def get_document_folder_name(
    document_type
):

    document_type = (
        document_type or ""
    ).lower()

    if (
        "itr" in document_type
        or "income tax" in document_type
        or "return of income" in document_type
    ):

        return "ITR"

    elif "gst" in document_type:

        return "GST"

    elif "aadhaar" in document_type:

        return "Aadhaar"

    elif "bank" in document_type:

        return "Bank Statements"

    elif "balance sheet" in document_type:

        return "Balance Sheet"

    elif "notice" in document_type:

        return "Notices"

    elif "pan" in document_type:

        return "PAN"

    return "Other"


# ---------------------------------------------------------
# Build logical folder structure
# ---------------------------------------------------------

def build_folder_structure(
    firm,
    client,
    document_type,
    assessment_year=None,
):

    folder_name = get_document_folder_name(
        document_type
    )

    structure = {

        "firm_folder": firm.firm_name,

        "client_folder": (
    f"{client.client_name} - {client.pan_number}"
    if client
    else "UNMATCHED"
),
        "document_folder": folder_name
    }

    normalized_year = normalize_assessment_year(assessment_year)
    if folder_name == "ITR" and normalized_year:
        structure["year_folder"] = f"AY {normalized_year}"

    return structure
