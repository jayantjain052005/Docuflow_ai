"""
DocuFlow AI - File Utilities
"""


def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """
    Check if the uploaded filename has an allowed extension.
    Prevents uploading dangerous file types.
    """
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def human_readable_size(num_bytes: int) -> str:
    """Convert bytes to a human-readable string like '2.3 MB'."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"
