import os
from pathlib import Path

from ocr.batch import BatchProcessor

TEST_FOLDER = r"C:\Users\Administrator\Documents\docuflow_ai\TEST"

# Get all images
files = []

for ext in ("*.jpg", "*.jpeg", "*.png", "*.pdf"):
    files.extend(
        Path(TEST_FOLDER).glob(ext)
    )

files = [str(f) for f in files]

print(f"\nFound {len(files)} files\n")

processor = BatchProcessor(
    workers=1,
    cache_dir=None,   # safer on Windows initially
    verbose=False
)

results = processor.process_batch(
    files,
    use_routing=False
)

print("\n================ RESULTS ================\n")

for r in results:

    print("=" * 60)

    print("FILE:", os.path.basename(r["file"]))

    print("TYPE:", r.get("document_type"))

    print("NAME:", r.get("detected_name", {}).get("value"))

    print(
        "PAN:",
        r.get("important_ids", {})
         .get("pan", {})
         .get("value")
    )

    print(
        "AADHAAR:",
        r.get("important_ids", {})
         .get("aadhaar", {})
         .get("value")
    )

    print(
        "GSTIN:",
        r.get("important_ids", {})
         .get("gstin", {})
         .get("value")
    )

    print(
        "YEAR:",
        r.get("year", {})
         .get("value")
    )

    print(
        "CONFIDENCE:",
        r.get("document_confidence")
    )

    print(
        "OCR SCORE:",
        r.get("ocr_score")
    )

    print("=" * 60)