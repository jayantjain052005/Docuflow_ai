"""
DocuFlow AI - Example Usage Script

Demonstrates how to use the OCR pipeline on different document types.
Run: python example_usage.py <path_to_document>
"""

import sys
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from ocr import process_document


def print_result(result: dict) -> None:
    """Pretty-print extraction results."""
    print("\n" + "═" * 60)
    print("  DocuFlow AI — Document Analysis Result")
    print("═" * 60)

    print(f"\n📄 Document Type     : {result['document_type']} ({result['document_confidence']}% confidence)")
    print(f"🔍 OCR Method        : {result['ocr_method']} (score: {result['ocr_score']})")

    name = result["detected_name"]
    print(f"\n👤 Detected Name     : {name.get('value') or 'NOT FOUND'} (conf: {name.get('confidence', 0)}%)")

    year = result["year"]
    print(f"📅 Assessment Year   : {year.get('value') or 'NOT FOUND'} (conf: {year.get('confidence', 0)}%)")

    ids = result["important_ids"]
    print("\n🆔 Extracted IDs:")
    for id_name, id_data in ids.items():
        val = id_data.get("value")
        conf = id_data.get("confidence", 0)
        if val:
            print(f"   {id_name.upper():10s}: {val} (conf: {conf}%)")
        else:
            print(f"   {id_name.upper():10s}: NOT FOUND")

    supp = result.get("supplemental", {})
    if supp:
        print("\n📎 Supplemental Info:")
        for key, data in supp.items():
            if isinstance(data, dict):
                val = data.get("value")
                if val:
                    print(f"   {key:25s}: {val}")
            elif isinstance(data, list) and data:
                print(f"   {key:25s}: {', '.join(str(d) for d in data[:3])}")

    print(f"\n📝 Summary: {result['summary']}")

    print("\n─── Raw Text Preview (first 500 chars) ───")
    print(result["raw_text"][:500])
    print("─" * 60)

    # Classification scores
    scores = result.get("_debug", {}).get("classification_scores", {})
    if scores:
        print("\n📊 Classification Scores:")
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for doc_type, score in sorted_scores[:5]:
            bar = "█" * min(int(score / 5), 20)
            print(f"   {doc_type:25s}: {score:4d}  {bar}")

    print("═" * 60 + "\n")


def demo_with_synthetic_itr_text():
    """
    Demonstrate the pipeline on a synthetic ITR acknowledgement text
    (simulates what OCR would extract from a real ITR acknowledgement).
    """
    print("\n[DEMO MODE: Synthetic ITR Acknowledgement Text]")

    # Simulated OCR output from an ITR acknowledgement
    # Includes typical OCR errors (O→0, spacing issues, etc.)
    synthetic_ocr = """
INCOME TAX DEPARTMENT

e-Filing Acknowledgement

Assessment Year: 2020-21

Name JAYANT JAIN
PAN DAKPJ38O1H
Form ITR-3

Acknowledgement No. 835621594201220

Filing Date 22-01-2020
e-Filing Date 22-01-2020

Total Income 850000
Total Tax Payable 0

Refund Amount 12500

BANGALORE
Central Processing Centre
"""

    # We test the correction + extraction directly
    from ocr.corrections import apply_all_corrections
    from ocr.metadata import extract_all_metadata
    from ocr.classifiers import classify_document, refine_classification

    corrected = apply_all_corrections(synthetic_ocr)

    print("\n[Corrected Text]")
    print(corrected)

    metadata = extract_all_metadata(corrected, ocr_score=85.0)
    classification = classify_document(corrected, ocr_score=85.0)
    classification = refine_classification(classification, metadata["important_ids"], corrected)

    # Build result
    from ocr import _build_summary
    result = {
        "document_type": classification["document_type"],
        "document_confidence": classification["document_confidence"],
        "detected_name": metadata["detected_name"],
        "year": metadata["year"],
        "important_ids": metadata["important_ids"],
        "supplemental": metadata.get("supplemental", {}),
        "summary": _build_summary(classification, metadata),
        "raw_text": corrected,
        "ocr_score": 85.0,
        "ocr_method": "demo",
        "_debug": {"classification_scores": classification.get("all_scores", {})},
    }

    print_result(result)
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python example_usage.py <document_path>")
        print("\nRunning built-in demo with synthetic ITR text...")
        demo_with_synthetic_itr_text()
        return

    filepath = sys.argv[1]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    if not Path(filepath).exists():
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    print(f"\nProcessing: {filepath}")
    result = process_document(filepath, verbose=verbose)
    print_result(result)

    # Save JSON output
    output_path = Path(filepath).stem + "_ocr_result.json"
    with open(output_path, "w") as f:
        # Convert result to JSON-serializable format
        json_result = {k: v for k, v in result.items() if k != "_debug"}
        json.dump(json_result, f, indent=2, ensure_ascii=False)
    print(f"JSON output saved to: {output_path}")


if __name__ == "__main__":
    main()
