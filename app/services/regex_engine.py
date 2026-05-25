import re


PATTERNS = {

    # -------------------------------------------------
    # PAN
    # Example: ABCDE1234F
    # -------------------------------------------------

    "pan": r"\b([A-Z]{5}[0-9]{4}[A-Z])\b",

    # -------------------------------------------------
    # Aadhaar
    # Example: 1234 5678 9012
    # -------------------------------------------------

    "aadhaar": r"\b([2-9]\d{3}\s?\d{4}\s?\d{4})\b",

    # -------------------------------------------------
    # GSTIN
    # -------------------------------------------------

    "gstin": r"\b(\d{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b",

    # -------------------------------------------------
    # IFSC
    # -------------------------------------------------

    "ifsc": r"\b([A-Z]{4}0[A-Z0-9]{6})\b",

    # -------------------------------------------------
    # Driving License
    # -------------------------------------------------

    "dl": r"\b([A-Z]{2}\d{2}\s?\d{11,13})\b",

    # -------------------------------------------------
    # Assessment Year
    # -------------------------------------------------

    "assessment_year": r"\b(?:AY|A\.Y\.|Assessment Year)[:\s]*(20\d{2}[-–]\d{2,4})\b",
}


# ---------------------------------------------------------
# Normalize OCR noise
# ---------------------------------------------------------

def clean_ocr_text(
    text
):

    # PAN spacing issue:
    # ABCDE 1234 F → ABCDE1234F

    text = re.sub(
        r"([A-Z]{5})\s([0-9]{4})\s([A-Z])",
        r"\1\2\3",
        text
    )

    return text


# ---------------------------------------------------------
# Extract all deterministic IDs
# ---------------------------------------------------------

def extract_ids(
    text
):

    clean = clean_ocr_text(text)

    extracted = {}

    # PAN
    pan_match = re.search(
        PATTERNS["pan"],
        clean
    )

    if pan_match:

        extracted["pan_number"] = (
            pan_match.group(1)
        )

    # Aadhaar
    aadhaar_match = re.search(
        PATTERNS["aadhaar"],
        clean
    )

    if aadhaar_match:

        extracted["aadhaar_number"] = (
            aadhaar_match
            .group(1)
            .replace(" ", "")
        )

    # GSTIN
    gst_match = re.search(
        PATTERNS["gstin"],
        clean
    )

    if gst_match:

        extracted["gstin"] = (
            gst_match.group(1)
        )

    # IFSC
    ifsc_match = re.search(
        PATTERNS["ifsc"],
        clean
    )

    if ifsc_match:

        extracted["ifsc"] = (
            ifsc_match.group(1)
        )

    # DL
    dl_match = re.search(
        PATTERNS["dl"],
        clean
    )

    if dl_match:

        extracted["dl_number"] = (
            dl_match.group(1)
        )

    # AY
    ay_match = re.search(
        PATTERNS["assessment_year"],
        clean
    )

    if ay_match:

        extracted["assessment_year"] = (
            ay_match.group(1)
        )

    return extracted