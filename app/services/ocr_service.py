"""
DocuFlow AI - OCR & Text Extraction Service
Handles PDF, JPG, and PNG files.
"""

import os
from PIL import Image
import cv2
import numpy as np
import pytesseract
def extract_text_from_file(filepath: str) -> str:
    """
    Extract text from a file based on its extension.
    Supports: .pdf, .jpg, .jpeg, .png
    Returns extracted text string (may be empty if OCR fails).
    """
    ext = os.path.splitext(
    filepath)[1].lower()

# Auto-rotate only images
    if ext in (".jpg",".jpeg",".png"):  

   
        filepath = auto_rotate_image(filepath)
        ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        return _extract_from_pdf(filepath)
    elif ext in (".jpg", ".jpeg", ".png"):
        return _extract_from_image(filepath)
    else:
        return ""

def _extract_from_pdf(filepath: str) -> str:
    """
    Extract text from scanned or digital PDFs.
    """

    try:
        import pdfplumber
        import pytesseract

        text_parts = []

        with pdfplumber.open(filepath) as pdf:

            for page in pdf.pages:

                # Try embedded text first
                page_text = page.extract_text()

                if (
                    page_text
                    and len(page_text.strip()) > 20
                ):

                    text_parts.append(page_text)

                else:

                    # OCR scanned PDF
                    img = page.to_image(
                        resolution=300
                    ).original

                    rotations = [
                        0,
                        90,
                        180,
                        270
                    ]

                    best_text = ""

                    def score_text(t):

                        common_words = [
                            "india",
                            "government",
                            "income",
                            "tax",
                            "name",
                            "father",
                            "birth",
                            "male",
                            "account",
                            "number",
                            "permanent",
                            "card"
                        ]

                        text_lower = t.lower()

                        score = 0

                        for word in common_words:

                            if word in text_lower:

                                score += 10

                        # add some alphanumeric weight too
                        score += sum(
                            c.isalnum()
                            for c in t
                        ) * 0.01

                        return score

                    for angle in rotations:

                        rotated = img.rotate(
                            angle,
                            expand=True
                        )

                        text = pytesseract.image_to_string(
                            rotated,
                            lang="eng"
                        )

                        if (
                            score_text(text)
                            > score_text(best_text)
                        ):

                            best_text = text

                    text_parts.append(best_text)

        final_text = (
            "\n".join(text_parts)
            .strip()
        )

        print("\nOCR TEXT\n")
        print(final_text[:1000])

        return final_text

    except Exception as e:

        return f"[PDF extraction error: {str(e)}]"


def _extract_from_image(filepath: str) -> str:
    """Extract text from image using OpenCV + Tesseract OCR."""

    try:
        import cv2
        import pytesseract

        # Read image
        img = cv2.imread(filepath)

        if img is None:
            return "[Could not read image]"

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Remove noise + improve OCR
        gray = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]

        # OCR
        text = pytesseract.image_to_string(
            gray,
            lang="eng",
            config="--psm 6"
        )

        return text.strip()

    except ImportError:
        return "[opencv-python or pytesseract not installed]"

    except Exception as e:
        return f"[Image OCR error: {str(e)}]"

def auto_rotate_image(
    image_path
):

    image = Image.open(image_path)

    rotations = [
        0,
        90,
        180,
        270
    ]

    best_text = ""
    best_rotation = 0

    for angle in rotations:

        rotated = image.rotate(
            angle,
            expand=True
        )

        temp_path = "temp_rotate.jpg"

        rotated.save(temp_path)

        text = pytesseract.image_to_string(
            temp_path
        )

        # choose rotation with most text
        if len(text) > len(best_text):

            best_text = text
            best_rotation = angle

    corrected = image.rotate(
        best_rotation,
        expand=True
    )

    corrected.save(image_path)

    return image_path