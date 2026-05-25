"""
DocuFlow AI — Organization Routes (Phase 1)
/org/dashboard, /org/staff/*, /org/clients/*
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash
from database import get_db
from app.utils.permissions import login_required, professional_required, organization_required, org_manager_required

org_bp = Blueprint("org", __name__, url_prefix="/org")

VALID_ORG_TYPES = ["CA Firm", "Law Firm", "Family Vault", "Accounting Firm", "Consultancy", "Other"]


# ── Professional Dashboard ─────────────────────────────────────────────────

@org_bp.route("/dashboard")
@professional_required
@organization_required
def dashboard():
    org_id  = session["organization_id"]
    user_id = session["user_id"]
    db      = get_db()

    org = db.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()

    staff_count = db.execute(
        "SELECT COUNT(*) AS c FROM organization_members WHERE organization_id = ?", (org_id,)
    ).fetchone()["c"]

    client_count = db.execute(
        "SELECT COUNT(*) AS c FROM clients WHERE organization_id = ?", (org_id,)
    ).fetchone()["c"]

    recent_clients = db.execute(
        """
        SELECT c.*, u.username AS added_by
          FROM clients c
          JOIN users u ON u.id = c.created_by
         WHERE c.organization_id = ?
         ORDER BY c.created_at DESC LIMIT 5
        """,
        (org_id,)
    ).fetchall()

    staff_members = db.execute(
        """
        SELECT u.id, u.username, u.email, u.phone, om.role, om.joined_at
          FROM organization_members om
          JOIN users u ON u.id = om.user_id
         WHERE om.organization_id = ?
         ORDER BY om.joined_at DESC
        """,
        (org_id,)
    ).fetchall()

    db.close()

    return render_template(
        "org/dashboard.html",
        org=org,
        staff_count=staff_count,
        client_count=client_count,
        recent_clients=recent_clients,
        staff_members=staff_members,
    )


# ── Staff Management ───────────────────────────────────────────────────────

@org_bp.route("/staff")
@org_manager_required
@organization_required
def staff_list():
    org_id = session["organization_id"]
    db = get_db()
    members = db.execute(
        """
        SELECT u.id, u.username, u.email, u.phone, u.is_active,
               om.role, om.joined_at
          FROM organization_members om
          JOIN users u ON u.id = om.user_id
         WHERE om.organization_id = ?
         ORDER BY om.joined_at DESC
        """,
        (org_id,)
    ).fetchall()
    db.close()
    return render_template("org/staff_list.html", members=members)


@org_bp.route("/staff/invite", methods=["GET", "POST"])
@org_manager_required
@organization_required
def invite_staff():
    org_id = session["organization_id"]

    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        phone     = request.form.get("phone", "").strip()
        email     = request.form.get("email", "").strip() or None
        password  = request.form.get("password", "")
        org_role  = request.form.get("org_role", "staff")

        if not username or not phone or not password:
            flash("Username, phone, and password are required.", "danger")
            return render_template("org/invite_staff.html")

        if org_role not in ("manager", "staff", "viewer"):
            org_role = "staff"

        db = get_db()

        # Check if user already exists
        existing = db.execute(
            "SELECT id FROM users WHERE username = ? OR phone = ?",
            (username, phone)
        ).fetchone()

        if existing:
            # Add existing user to org if not already a member
            member = db.execute(
                "SELECT id FROM organization_members WHERE organization_id=? AND user_id=?",
                (org_id, existing["id"])
            ).fetchone()
            if member:
                db.close()
                flash("This user is already a member of your organization.", "warning")
                return redirect(url_for("org.staff_list"))

            db.execute(
                "INSERT INTO organization_members (organization_id, user_id, role) VALUES (?,?,?)",
                (org_id, existing["id"], org_role)
            )
            db.execute(
                "UPDATE users SET organization_id=?, role='staff' WHERE id=?",
                (org_id, existing["id"])
            )
            db.commit()
            db.close()
            flash(f"Existing user '{username}' added to your organization.", "success")
            return redirect(url_for("org.staff_list"))

        # Create new staff user
        pw_hash = generate_password_hash(password)
        cur = db.execute(
            """
            INSERT INTO users (username, email, phone, password_hash, role, organization_id, is_verified, is_active)
            VALUES (?, ?, ?, ?, 'staff', ?, 0, 1)
            """,
            (username, email, phone, pw_hash, org_id)
        )
        new_user_id = cur.lastrowid
        db.execute(
            "INSERT INTO organization_members (organization_id, user_id, role) VALUES (?,?,?)",
            (org_id, new_user_id, org_role)
        )
        db.commit()
        db.close()
        flash(f"Staff member '{username}' invited successfully.", "success")
        return redirect(url_for("org.staff_list"))

    return render_template("org/invite_staff.html")


@org_bp.route("/staff/<int:member_id>/remove", methods=["POST"])
@org_manager_required
@organization_required
def remove_staff(member_id):
    org_id = session["organization_id"]
    db = get_db()
    member = db.execute(
        "SELECT om.role, om.user_id FROM organization_members om WHERE om.organization_id=? AND om.user_id=?",
        (org_id, member_id)
    ).fetchone()

    if not member:
        db.close()
        flash("Member not found.", "danger")
        return redirect(url_for("org.staff_list"))

    if member["role"] == "owner":
        db.close()
        flash("Cannot remove the organization owner.", "danger")
        return redirect(url_for("org.staff_list"))

    db.execute(
        "DELETE FROM organization_members WHERE organization_id=? AND user_id=?",
        (org_id, member_id)
    )
    db.commit()
    db.close()
    flash("Staff member removed.", "success")
    return redirect(url_for("org.staff_list"))


# ── Client Management ──────────────────────────────────────────────────────

@org_bp.route("/clients")
@organization_required
@login_required
def client_list():
    org_id = session["organization_id"]
    db = get_db()
    clients = db.execute(
        """
        SELECT c.*, u.username AS added_by,
               (SELECT COUNT(*) FROM authorized_numbers an WHERE an.client_id = c.id) AS auth_count
          FROM clients c
          JOIN users u ON u.id = c.created_by
         WHERE c.organization_id = ?
         ORDER BY c.created_at DESC
        """,
        (org_id,)
    ).fetchall()
    db.close()
    return render_template("org/client_list.html", clients=clients)


@org_bp.route("/clients/add", methods=["GET", "POST"])
@organization_required
@login_required
def add_client():
    org_id  = session["organization_id"]
    user_id = session["user_id"]

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email     = request.form.get("email", "").strip() or None
        phone     = request.form.get("primary_phone", "").strip() or None

        if not full_name:
            flash("Client full name is required.", "danger")
            return render_template("org/add_client.html")

        db = get_db()
        cur = db.execute(
            """
            INSERT INTO clients (organization_id, full_name, email, primary_phone, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (org_id, full_name, email, phone, user_id)
        )
        client_id = cur.lastrowid

        # Add authorized numbers
        phones = request.form.getlist("auth_phone")
        labels = request.form.getlist("auth_label")
        for p, l in zip(phones, labels):
            p = p.strip()
            l = l.strip()
            if p:
                db.execute(
                    "INSERT INTO authorized_numbers (client_id, phone, label) VALUES (?,?,?)",
                    (client_id, p, l or "Contact")
                )

        db.commit()
        db.close()
        flash(f"Client '{full_name}' added successfully.", "success")
        return redirect(url_for("org.client_list"))

    return render_template("org/add_client.html")


@org_bp.route("/clients/<int:client_id>")
@organization_required
@login_required
def view_client(client_id):
    org_id = session["organization_id"]
    db = get_db()

    client = db.execute(
        "SELECT * FROM clients WHERE id = ? AND organization_id = ?",
        (client_id, org_id)
    ).fetchone()

    if not client:
        db.close()
        flash("Client not found.", "danger")
        return redirect(url_for("org.client_list"))

    auth_numbers = db.execute(
        "SELECT * FROM authorized_numbers WHERE client_id = ? ORDER BY created_at",
        (client_id,)
    ).fetchall()

    db.close()
    return render_template("org/view_client.html", client=client, auth_numbers=auth_numbers)


@org_bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@organization_required
@login_required
def edit_client(client_id):
    org_id = session["organization_id"]
    db = get_db()

    client = db.execute(
        "SELECT * FROM clients WHERE id = ? AND organization_id = ?",
        (client_id, org_id)
    ).fetchone()

    if not client:
        db.close()
        flash("Client not found.", "danger")
        return redirect(url_for("org.client_list"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email     = request.form.get("email", "").strip() or None
        phone     = request.form.get("primary_phone", "").strip() or None

        if not full_name:
            flash("Client full name is required.", "danger")
            auth_numbers = db.execute(
                "SELECT * FROM authorized_numbers WHERE client_id=?", (client_id,)
            ).fetchall()
            db.close()
            return render_template("org/edit_client.html", client=client, auth_numbers=auth_numbers)

        db.execute(
            "UPDATE clients SET full_name=?, email=?, primary_phone=? WHERE id=?",
            (full_name, email, phone, client_id)
        )
        db.commit()
        db.close()
        flash("Client updated.", "success")
        return redirect(url_for("org.view_client", client_id=client_id))

    auth_numbers = db.execute(
        "SELECT * FROM authorized_numbers WHERE client_id=?", (client_id,)
    ).fetchall()
    db.close()
    return render_template("org/edit_client.html", client=client, auth_numbers=auth_numbers)


# ── Authorized Numbers ─────────────────────────────────────────────────────

@org_bp.route("/clients/<int:client_id>/numbers/add", methods=["POST"])
@organization_required
@login_required
def add_authorized_number(client_id):
    org_id = session["organization_id"]
    db = get_db()
    client = db.execute(
        "SELECT id FROM clients WHERE id=? AND organization_id=?", (client_id, org_id)
    ).fetchone()
    if not client:
        db.close()
        flash("Client not found.", "danger")
        return redirect(url_for("org.client_list"))

    phone = request.form.get("phone", "").strip()
    label = request.form.get("label", "Contact").strip()

    if phone:
        db.execute(
            "INSERT INTO authorized_numbers (client_id, phone, label) VALUES (?,?,?)",
            (client_id, phone, label)
        )
        db.commit()
        flash("Authorized number added.", "success")
    db.close()
    return redirect(url_for("org.view_client", client_id=client_id))


@org_bp.route("/numbers/<int:number_id>/delete", methods=["POST"])
@organization_required
@login_required
def delete_authorized_number(number_id):
    db = get_db()
    db.execute("DELETE FROM authorized_numbers WHERE id=?", (number_id,))
    db.commit()
    db.close()
    flash("Number removed.", "success")
    return redirect(request.referrer or url_for("org.client_list"))
