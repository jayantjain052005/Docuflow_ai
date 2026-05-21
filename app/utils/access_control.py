"""
DocuFlow AI — Access Control Middleware
========================================
All permission checks live here. Routes call these helpers;
they never write their own DB permission queries.

Permission hierarchy (ordered):
  owner > editor > contributor > viewer

Future: swap get_db() with SQLAlchemy session for PostgreSQL.
"""

from functools import wraps
from datetime import datetime, timezone
from flask import session, abort, redirect, url_for, flash
from database import get_db
from app.models.user import User
from app.models.firm import Firm

# ── Permission rank map ────────────────────────────────────────────────────
PERMISSION_RANK = {
    "owner":       4,
    "editor":      3,
    "contributor": 2,
    "viewer":      1,
}


def _utcnow():
    return datetime.now(timezone.utc)


# ── Core helpers ───────────────────────────────────────────────────────────

def get_document_permission(document_id: int, user_id: int) -> str | None:
    """
    Return the effective permission string for user_id on document_id.

    Returns:
        'owner'       – user owns the document
        'editor'      – shared with editor rights
        'contributor' – shared with contributor rights
        'viewer'      – shared with viewer rights
        None          – no access at all
    """
    db = get_db()

    # Check ownership first
    doc = db.execute(
        "SELECT owner_user_id FROM documents WHERE id = ? AND is_deleted = 0",
        (document_id,)
    ).fetchone()

    if not doc:
        db.close()
        return None

    if doc["owner_user_id"] == user_id:
        db.close()
        return "owner"

    # Check shared access
    access = db.execute(
        """
        SELECT permission, expires_at
          FROM document_access
         WHERE document_id   = ?
           AND shared_with_id = ?
        """,
        (document_id, user_id)
    ).fetchone()

    db.close()

    if not access:
        return None

    # Check expiry
    if access["expires_at"]:
        try:
            exp = datetime.fromisoformat(access["expires_at"])
            # Make timezone-aware if naive
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if _utcnow() > exp:
                return None   # Access expired
        except ValueError:
            pass

    return access["permission"]


def can(permission_required: str, document_id: int, user_id: int) -> bool:
    """
    Return True if user_id holds at least permission_required on document_id.

    Example:
        can('viewer', doc_id, user_id)      # read access
        can('contributor', doc_id, user_id) # upload access
        can('editor', doc_id, user_id)      # edit/delete access
        can('owner', doc_id, user_id)       # owner-only actions
    """
    effective = get_document_permission(document_id, user_id)
    if not effective:
        return False
    return PERMISSION_RANK.get(effective, 0) >= PERMISSION_RANK.get(permission_required, 99)


# ── Decorators ─────────────────────────────────────────────────────────────

def login_required(f):
    """Redirect to login if user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))

        user = User.query.get(session["user_id"])
        if not user or not user.is_active:
            session.clear()
            flash("Account is disabled.", "warning")
            return redirect(url_for("auth.login"))

        if user.role != User.ROLE_SUPER_ADMIN:
            firm = Firm.query.get(user.firm_id)
            if not firm or not firm.is_active:
                session.clear()
                flash(
                    "This firm has been deactivated. Contact your administrator.",
                    "warning",
                )
                return redirect(url_for("auth.login"))

        if "firm_id" not in session:
            session["firm_id"] = user.firm_id
            session["role"] = user.role
            session["full_name"] = user.full_name

        return f(*args, **kwargs)
    return decorated


def require_document_permission(required: str, id_kwarg: str = "doc_id"):
    """
    Decorator factory that enforces a minimum permission on a document.

    Usage:
        @require_document_permission('viewer')
        def view_document(doc_id):
            ...

        @require_document_permission('owner', id_kwarg='document_id')
        def share_document(document_id):
            ...
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            document_id = kwargs.get(id_kwarg)
            user_id = session["user_id"]
            if not can(required, document_id, user_id):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Audit logging ──────────────────────────────────────────────────────────

def log_action(action: str, entity_type: str, entity_id: int = None,
               detail: str = None, user_id: int = None, ip: str = None):
    """
    Write one row to audit_log. Fire-and-forget — never raises.
    """
    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, detail, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, entity_type, entity_id, detail, ip)
        )
        db.commit()
        db.close()
    except Exception as exc:
        # Never crash the app over logging
        print(f"[AUDIT LOG ERROR] {exc}")
