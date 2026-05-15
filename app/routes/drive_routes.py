from flask import Blueprint, request, jsonify
from app.services.drive_service import upload_file, list_files
from flask import redirect, url_for
drive_bp = Blueprint('drive', __name__)


@drive_bp.route('/upload', methods=['POST'])
def upload():

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files['file']

    uploaded = upload_file(uploaded_file)
    import os
    from werkzeug.utils import secure_filename

    from app.services.ocr_service import extract_text_from_file
    from app.services.groq_service import extract_metadata


    # Save temporary file
    temp_path = os.path.join(
        "uploads",
        secure_filename(uploaded_file.filename)
    )

    uploaded_file.seek(0)
    uploaded_file.save(temp_path)

    # OCR extraction
    ocr_text = extract_text_from_file(temp_path)

    print("\nOCR TEXT:\n")
    print(ocr_text)

    # Groq analysis
    metadata = extract_metadata(ocr_text)

    print("\nAI METADATA:\n")
    print(metadata)

    # Cleanup
    os.remove(temp_path)

    # from flask import redirect, url_for

    return redirect(url_for("documents.dashboard"))


@drive_bp.route('/files', methods=['GET'])
def files():

    return jsonify({
        "files": list_files()
    })