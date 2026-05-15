from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text

from app.extensions import db
from app.utils.access_control import login_required


sharing_bp = Blueprint("sharing", __name__)


@sharing_bp.route("/shared-with-me")
@login_required
def shared_with_me():
    docs = []
    try:
        docs = db.session.execute(
            text(
                """
                SELECT
                    d.id,
                    d.filename,
                    d.document_type,
                    d.uploaded_at AS shared_at,
                    d.uploaded_by AS owner_user_id,
                    u.full_name AS owner_name,
                    da.permission,
                    da.expires_at
                FROM document_access da
                JOIN documents d ON d.id = da.document_id
                LEFT JOIN users u ON u.id = da.shared_by_id
                WHERE da.shared_with_id = :user_id
                ORDER BY da.created_at DESC
                """
            ),
            {"user_id": session["user_id"]},
        ).mappings().all()
    except Exception:
        db.session.rollback()
    return render_template("shared_with_me.html", docs=docs)


@sharing_bp.route("/shared-by-me")
@login_required
def shared_by_me():
    shares = []
    try:
        shares = db.session.execute(
            text(
                """
                SELECT
                    d.id AS doc_id,
                    d.filename,
                    d.document_type,
                    u.id AS recipient_id,
                    u.full_name AS recipient_name,
                    u.mobile AS recipient_phone,
                    da.permission,
                    da.expires_at,
                    da.created_at AS shared_at
                FROM document_access da
                JOIN documents d ON d.id = da.document_id
                LEFT JOIN users u ON u.id = da.shared_with_id
                WHERE da.shared_by_id = :user_id
                ORDER BY da.created_at DESC
                """
            ),
            {"user_id": session["user_id"]},
        ).mappings().all()
    except Exception:
        db.session.rollback()
    return render_template("shared_by_me.html", shares=shares)


@sharing_bp.route("/documents/<int:doc_id>/share", methods=["POST"])
@login_required
def share_document(doc_id):
    target = request.form.get("phone_or_username", "").strip()
    permission = request.form.get("permission", "viewer")
    expires_at = request.form.get("expires_at") or None

    if permission not in {"viewer", "contributor", "editor"}:
        permission = "viewer"

    user = db.session.execute(
        text(
            """
            SELECT id FROM users
            WHERE id != :current_user_id
              AND (full_name = :target OR email = :target OR mobile = :target)
            LIMIT 1
            """
        ),
        {"current_user_id": session["user_id"], "target": target},
    ).first()

    if not user:
        flash("User not found", "danger")
        return redirect(url_for("documents.view_document", doc_id=doc_id))

    db.session.execute(
        text(
            """
            INSERT INTO document_access
                (document_id, shared_by_id, shared_with_id, permission, expires_at)
            VALUES
                (:doc_id, :shared_by_id, :shared_with_id, :permission, :expires_at)
            ON CONFLICT(document_id, shared_with_id) DO UPDATE SET
                permission = excluded.permission,
                expires_at = excluded.expires_at
            """
        ),
        {
            "doc_id": doc_id,
            "shared_by_id": session["user_id"],
            "shared_with_id": user.id,
            "permission": permission,
            "expires_at": expires_at,
        },
    )
    db.session.commit()
    flash("Document access granted", "success")
    return redirect(url_for("documents.view_document", doc_id=doc_id))


@sharing_bp.route("/documents/<int:doc_id>/revoke/<int:target_user_id>", methods=["POST"])
@login_required
def revoke_access(doc_id, target_user_id):
    db.session.execute(
        text(
            """
            DELETE FROM document_access
            WHERE document_id = :doc_id
              AND shared_by_id = :shared_by_id
              AND shared_with_id = :target_user_id
            """
        ),
        {
            "doc_id": doc_id,
            "shared_by_id": session["user_id"],
            "target_user_id": target_user_id,
        },
    )
    db.session.commit()
    flash("Document access revoked", "success")
    return redirect(request.referrer or url_for("sharing.shared_by_me"))
