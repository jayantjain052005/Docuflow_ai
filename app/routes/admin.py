"""
DocuFlow AI — Admin Dashboard Routes (Phase 1 Upgrade)
/admin, /admin/users, /admin/organizations
"""

from types import SimpleNamespace

from flask import Blueprint, render_template, redirect, url_for, flash
from app.utils.permissions import super_admin_required

from app.models.firm import Firm
from app.models.user import User
from app.models.document import Document
from app.models.client import Client

from app.utils.access_control import (
    login_required
)

admin_bp = Blueprint(
    "admin",
    __name__
)


@admin_bp.route("/admin/dashboard")
@login_required
def super_admin_dashboard():

    total_firms = Firm.query.count()

    total_users = User.query.count()

    total_documents = Document.query.count()

    return render_template(
        "admin/dashboard.html",
        total_firms=total_firms,
        total_users=total_users,
        total_documents=total_documents
    )

@admin_bp.route("/")
@super_admin_required
def admin_dashboard():
    return redirect(url_for("admin.super_admin_dashboard"))


@admin_bp.route("/users")
@super_admin_required
def user_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/user_list.html", users=users)


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@super_admin_required
def toggle_user_active(user_id):
    from app.extensions import db

    user = User.query.get(user_id)
    if user:
        user.is_active = not user.is_active
        db.session.commit()
        flash(f"User {'activated' if user.is_active else 'deactivated'}.", "success")
    return redirect(url_for("admin.user_list"))


@admin_bp.route("/organizations")
@super_admin_required
def org_list():
    firms = Firm.query.order_by(Firm.created_at.desc()).all()
    orgs = [
        SimpleNamespace(
            id=firm.id,
            firm_name=firm.firm_name,
            email=firm.email,
            mobile=firm.mobile,
            users=firm.users,
            client_count=Client.query.filter_by(firm_id=firm.id).count(),
            created_at=firm.created_at,
            is_active=firm.is_active,
        )
        for firm in firms
    ]
    return render_template("admin/org_list.html", orgs=orgs)


@admin_bp.route("/organizations/<int:firm_id>/toggle-active", methods=["POST"])
@super_admin_required
def toggle_firm_active(firm_id):
    from app.extensions import db

    firm = Firm.query.get_or_404(firm_id)
    firm.is_active = not firm.is_active

    for user in firm.users:
        user.is_active = firm.is_active

    db.session.commit()

    if firm.is_active:
        flash(f"Firm “{firm.firm_name}” activated. All users can sign in again.", "success")
    else:
        flash(f"Firm “{firm.firm_name}” deactivated. All users under this firm are disabled.", "success")

    return redirect(url_for("admin.org_list"))
