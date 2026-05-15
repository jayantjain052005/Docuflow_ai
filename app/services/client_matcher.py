from sqlalchemy import func

from app.models.client import Client


def normalize_aadhaar(value):
    return "".join(ch for ch in (value or "") if ch.isdigit())


def normalize_pan(value):
    return "".join(ch for ch in (value or "") if ch.isalnum()).upper()


def pan_from_gstin(value):
    gstin = normalize_pan(value)
    if len(gstin) != 15:
        return None

    pan = gstin[2:12]
    if len(pan) != 10:
        return None

    return pan


def match_client(
    extracted_data,
    firm_id
):

    possible_matches = []

    important_ids = extracted_data.get(
    "important_ids",
    {}
)

    pan_number = important_ids.get(
    "pan"
)

    gstin = important_ids.get(
        "gstin"
    )

    aadhaar_number = normalize_aadhaar(
        important_ids.get("aadhaar")
    )

    mobile = extracted_data.get(
        "mobile"
    )

    name = extracted_data.get(
        "name"
    )
    document_type = extracted_data.get(
    "document_type",
    ""
).lower()

    # -------------------------------------------------
    # 1. PAN Match (Highest confidence)
    # -------------------------------------------------

    if pan_number:

        client = Client.query.filter_by(
            firm_id=firm_id,
            is_active=True,
        ).filter(
            func.upper(Client.pan_number) == normalize_pan(pan_number)
        ).first()

        if client:

            return {
                "client": client,
                "confidence": 1.0,
                "reason": "PAN match",
                "ambiguous": False
            }

    gst_pan_number = pan_from_gstin(gstin)

    if gst_pan_number:

        client = Client.query.filter_by(
            firm_id=firm_id,
            is_active=True,
        ).filter(
            func.upper(Client.pan_number) == gst_pan_number
        ).first()

        if client:

            return {
                "client": client,
                "confidence": 0.98,
                "reason": "GSTIN embedded PAN match",
                "ambiguous": False
            }

    

    # -------------------------------------------------
# 2. Aadhaar Match
# -------------------------------------------------

    # -------------------------------------------------
    # 2. Aadhaar Match
    # -------------------------------------------------

    if aadhaar_number:

        normalized_client_aadhaar = func.replace(
            func.replace(Client.aadhaar_number, " ", ""),
            "-",
            "",
        )
        aadhaar_matches = (
            Client.query
            .filter(Client.firm_id == firm_id)
            .filter(Client.is_active == True)
            .filter(normalized_client_aadhaar == aadhaar_number)
            .all()
        )

        # -------------------------------------------------
        # Single Aadhaar Match
        # -------------------------------------------------

        if len(aadhaar_matches) == 1:

            return {
                "client": aadhaar_matches[0],
                "confidence": 0.95,
                "reason": "Unique Aadhaar match",
                "ambiguous": False
            }

        # -------------------------------------------------
        # Multiple PANs share Aadhaar
        # -------------------------------------------------

        elif len(aadhaar_matches) > 1:

            identity_docs = [
                "aadhaar",
                "passport",
                "driving license"
            ]

            # Identity documents should go to
            # primary personal PAN
            if any(
                doc in document_type
                for doc in identity_docs
            ):

                for client in aadhaar_matches:

                    if (
                        client.client_type == "personal"
                        and client.is_primary_personal
                    ):

                        return {
                            "client": client,
                            "confidence": 0.92,
                            "reason": "Primary personal PAN selected",
                            "ambiguous": False
                        }

            # Otherwise ambiguous
            return {
                "client": None,
                "confidence": 0.50,
                "reason": "Multiple PANs linked to Aadhaar",
                "ambiguous": True,
                "possible_matches": aadhaar_matches
            }
        
        # -------------------------------------------------
    # 3. Unique Name Match
    # -------------------------------------------------

    if name:

        normalized_name = (
            name.lower().strip()
        )

        name_matches = []

        all_clients = Client.query.filter_by(
            firm_id=firm_id,
            is_active=True
        ).all()

        for client in all_clients:

            client_name = (
                client.client_name
                .lower()
                .strip()
            )
            print("\nNAME MATCH DEBUG\n")
            print("OCR NAME:", normalized_name)
            print("DB NAME:", client_name)
            if (
    normalized_name in client_name
    or client_name in normalized_name
):

                name_matches.append(client)

        # Only one exact name match
        if len(name_matches) == 1:

            return {
                "client": name_matches[0],
                "confidence": 0.75,
                "reason": "Unique name match",
                "ambiguous": False
            }

        # Multiple same names
        elif len(name_matches) > 1:

            return {
                "client": None,
                "confidence": 0.40,
                "reason": "Multiple clients share same name",
                "ambiguous": True,
                "possible_matches": name_matches
            }
        # -------------------------------------------------
    # No Match
    # -------------------------------------------------

    return {
        "client": None,
        "confidence": 0,
        "reason": "No reliable match",
        "ambiguous": False
    }
    print("\nMATCH RESULT\n")
    print(extracted_data)
    print("\nAADHAAR MATCHES\n")
    print(aadhaar_matches)
