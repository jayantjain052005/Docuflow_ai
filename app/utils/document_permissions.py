from flask import session
from database import get_db


def can_access_document(doc_id, user_id=None):

    if user_id is None:
        user_id = session.get("user_id")

    db = get_db()

    # Get document
    doc = db.execute(
        """
        SELECT *
        FROM documents
        WHERE id = ?
        AND is_deleted = 0
        """,
        (doc_id,)
    ).fetchone()

    if not doc:
        db.close()
        return False

    # Owner access
    if doc["owner_user_id"] == user_id:
        db.close()
        return True

    # Organization shared access
    if doc["visibility"] == "organization":

        member = db.execute(
            """
            SELECT id
            FROM organization_members
            WHERE organization_id = ?
            AND user_id = ?
            """,
            (
                doc["organization_id"],
                user_id
            )
        ).fetchone()

        if member:
            db.close()
            return True

    # Explicit shared access
    shared = db.execute(
        """
        SELECT id
        FROM document_shares
        WHERE document_id = ?
        AND shared_with_user_id = ?
        """,
        (
            doc_id,
            user_id
        )
    ).fetchone()

    db.close()

    return bool(shared)