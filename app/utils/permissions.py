"""
DocuFlow AI — RBAC Permission Decorators (Phase 1)
app/utils/permissions.py

Global roles:
    super_admin   – full system access
    professional  – owns an organization, can manage clients/staff
    staff         – member of an organization
    client        – end-user client (read-only view)
    self_user     – standalone personal user

Organization member roles:
    owner    – created the org
    manager  – can invite staff, manage clients
    staff    – can upload/view documents
    viewer   – read-only
"""

from functools import wraps
from flask import session, abort, redirect, url_for, flash

# ── Role hierarchy (higher = more powerful) ────────────────────────────────
GLOBAL_ROLE_RANK = {
    "super_admin":  100,
    "professional":  50,
    "staff":         20,
    "client":        10,
    "self_user":      5,
}

ORG_ROLE_RANK = {
    "owner":   4,
    "manager": 3,
    "staff":   2,
    "viewer":  1,
}


def _current_role() -> str:
    return session.get("role", "self_user")


def _current_user_id():
    return session.get("user_id")


def _current_org_id():
    return session.get("organization_id")


# ── Core guard helpers ─────────────────────────────────────────────────────

def has_global_role(required: str) -> bool:
    """Return True if the session user holds at least `required` global role."""
    rank = GLOBAL_ROLE_RANK.get(_current_role(), 0)
    return rank >= GLOBAL_ROLE_RANK.get(required, 9999)


def has_org_role(required: str, org_id: int = None) -> bool:
    """
    Return True if the session user holds at least `required` role
    in the given organization (defaults to session org).
    """
    from database import get_db
    check_org = org_id or _current_org_id()
    if not check_org:
        return False
    db = get_db()
    row = db.execute(
        "SELECT role FROM organization_members WHERE organization_id=? AND user_id=?",
        (check_org, _current_user_id())
    ).fetchone()
    db.close()
    if not row:
        return False
    return ORG_ROLE_RANK.get(row["role"], 0) >= ORG_ROLE_RANK.get(required, 9999)


# ── Decorator factory ──────────────────────────────────────────────────────

def _role_required(check_fn, error_msg="Access denied."):
    """Generic decorator factory for role checks."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth.login"))
            if not check_fn():
                flash(error_msg, "danger")
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Public decorators ──────────────────────────────────────────────────────

def login_required(f):
    """Redirect to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    """Only super_admin may enter."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if _current_role() != "super_admin":
            flash("Super-admin access required.", "danger")
            abort(403)
        return f(*args, **kwargs)
    return decorated


# Kept as alias so existing admin_bp code still works
admin_required = super_admin_required


def professional_required(f):
    """Only professional (or higher) may enter."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not has_global_role("professional"):
            flash("Professional account required.", "danger")
            abort(403)
        return f(*args, **kwargs)
    return decorated


def organization_required(f):
    """User must belong to an organization (session must have organization_id)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not _current_org_id():
            flash("You must belong to an organization to access this page.", "warning")
            return redirect(url_for("documents.dashboard"))
        return f(*args, **kwargs)
    return decorated


def org_manager_required(f):
    """User must be an org owner or manager."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not has_org_role("manager"):
            flash("Organization manager access required.", "danger")
            abort(403)
        return f(*args, **kwargs)
    return decorated
