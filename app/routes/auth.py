from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from app.extensions import db
from app.models.user import User
from app.models.firm import Firm


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():

    if "user_id" in session:
        return redirect(url_for("documents.dashboard"))

    return redirect(url_for("auth.login"))


# -------------------------------------------------------------------
# Register
# -------------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    admin_create = (
        request.args.get("mode") == "professional"
        and session.get("role") == User.ROLE_SUPER_ADMIN
    )

    if "user_id" in session and not admin_create:
        return redirect(url_for("documents.dashboard"))

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        mobile = request.form.get(
            "mobile",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        firm_name = request.form.get(
            "firm_name",
            ""
        ).strip()

        # Validation
        if not full_name or not email or not password:

            flash(
                "Please fill all required fields",
                "danger"
            )

            return render_template("register.html")

        if password != confirm_password:

            flash(
                "Passwords do not match",
                "danger"
            )

            return render_template("register.html")

        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:

            flash(
                "Email already exists",
                "danger"
            )

            return render_template("register.html")

        # Create Firm
        firm = Firm(
            firm_name=firm_name,
            email=email,
            mobile=mobile
        )

        db.session.add(firm)
        db.session.flush()

        # Create Firm Admin User
        user = User(
            firm_id=firm.id,
            full_name=full_name,
            email=email,
            mobile=mobile,
            role=User.ROLE_FIRM_ADMIN
        )

        user.set_password(password)

        db.session.add(user)

        db.session.commit()

        flash(
            "Registration successful. Please login.",
            "success"
        )

        if session.get("role") == User.ROLE_SUPER_ADMIN:
            return redirect(url_for("admin.super_admin_dashboard"))

        return redirect(url_for("auth.login"))

    return render_template(
        "register.html",
        admin_create=admin_create
    )


# -------------------------------------------------------------------
# Login
# -------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect(url_for("documents.dashboard"))

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user and user.check_password(password):

            if not user.is_active:

                flash(
                    "Account is disabled",
                    "warning"
                )

                return render_template("login.html")

            if user.role != User.ROLE_SUPER_ADMIN:
                firm = Firm.query.get(user.firm_id)
                if not firm or not firm.is_active:
                    flash(
                        "This firm has been deactivated. Contact your administrator.",
                        "warning"
                    )
                    return render_template("login.html")

            session.clear()

            session["user_id"] = user.id
            session["firm_id"] = user.firm_id
            session["role"] = user.role
            session["full_name"] = user.full_name

            flash(
                f"Welcome back, {user.full_name}",
                "success"
            )

            if user.role == "super_admin":

                return redirect(
                url_for("admin.super_admin_dashboard")
            )

            elif user.role == "staff":

                return redirect(
                    url_for("documents.dashboard")
                )

            else:

                return redirect(
                url_for("documents.dashboard")
            )

        flash(
            "Invalid email or password",
            "danger"
        )

    return render_template("login.html")


# -------------------------------------------------------------------
# Logout
# -------------------------------------------------------------------

@auth_bp.route("/logout")
def logout():

    session.clear()

    flash(
        "Logged out successfully",
        "info"
    )

    return redirect(url_for("auth.login"))
