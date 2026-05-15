from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)
from app.models.firm import Firm

from app.services.drive_service import (
    get_or_create_folder,
    move_folder,
    FOLDER_ID
)
from app.extensions import db

from app.models.client import Client

from app.utils.access_control import login_required


clients_bp = Blueprint(
    "clients",
    __name__
)


def normalize_aadhaar(value):
    return "".join(ch for ch in (value or "") if ch.isdigit())


def get_firm_client_or_404(client_id):
    client = Client.query.get_or_404(client_id)
    if client.firm_id != session["firm_id"]:
        flash("Unauthorized", "danger")
        return None
    return client


@clients_bp.route("/clients")
@login_required
def client_list():

    clients = Client.query.filter_by(
        firm_id=session["firm_id"]
    ).all()

    return render_template(
        "clients/list.html",
        clients=clients
    )


@clients_bp.route(
    "/clients/add",
    methods=["GET", "POST"]
)
@login_required
def add_client():

    if request.method == "POST":

        client = Client(

            firm_id=session["firm_id"],

            client_name=request.form.get(
                "client_name"
            ),

            mobile=request.form.get(
                "mobile"
            ),

            email=request.form.get(
                "email"
            ),

            pan_number=request.form.get(
                "pan_number"
            ),

            aadhaar_number=(
                normalize_aadhaar(
                    request.form.get("aadhaar_number")
                )
            ),

            client_type=request.form.get("client_type"),

            is_primary_personal=bool(
                request.form.get("is_primary_personal")
            )
        )

        db.session.add(client)

        db.session.commit()

        flash(
            "Client added successfully",
            "success"
        )

        return redirect(
            url_for("clients.client_list")
        )

    return render_template(
        "clients/add.html"
    )


@clients_bp.route("/clients/<int:client_id>")
@login_required
def view_client(client_id):
    client = get_firm_client_or_404(client_id)
    if not client:
        return redirect(url_for("clients.client_list"))

    return render_template(
        "clients/view.html",
        client=client
    )


@clients_bp.route(
    "/clients/edit/<int:client_id>",
    methods=["GET", "POST"]
)
@login_required
def edit_client(client_id):
    client = get_firm_client_or_404(client_id)
    if not client:
        return redirect(url_for("clients.client_list"))

    if request.method == "POST":
        client.client_name = request.form.get("client_name")
        client.mobile = request.form.get("mobile")
        client.email = request.form.get("email")
        client.pan_number = request.form.get("pan_number")
        client.aadhaar_number = normalize_aadhaar(
            request.form.get("aadhaar_number")
        )
        client.client_type = request.form.get("client_type")
        client.is_primary_personal = bool(
            request.form.get("is_primary_personal")
        )

        db.session.commit()
        flash("Client updated successfully", "success")
        return redirect(url_for("clients.view_client", client_id=client.id))

    return render_template(
        "clients/edit.html",
        client=client
    )


@clients_bp.route(
    "/clients/<int:client_id>/toggle-active",
    methods=["POST"]
)
@login_required
def toggle_client_active(client_id):
    client = get_firm_client_or_404(client_id)
    if not client:
        return redirect(url_for("clients.client_list"))

    client.is_active = not client.is_active
    db.session.commit()

    flash(
        (
            "Client activated successfully"
            if client.is_active
            else "Client deactivated successfully"
        ),
        "success",
    )
    return redirect(url_for("clients.client_list"))


@clients_bp.route(
    "/clients/delete/<int:client_id>",
    methods=["POST"]
)
@login_required
def delete_client(client_id):

    client = Client.query.get_or_404(
        client_id
    )

    # Security:
    # only same firm can delete
    if (
        client.firm_id
        != session["firm_id"]
    ):

        flash(
            "Unauthorized",
            "danger"
        )

        return redirect(
            url_for("clients.client_list")
        )
        # -------------------------------------------------
    # Move client Drive folder to Deleted_Clients
    # -------------------------------------------------

    firm = Firm.query.get(
        session["firm_id"]
    )

    # Firm root folder
    firm_folder_id = get_or_create_folder(
        firm.firm_name,
        parent_id=FOLDER_ID
    )

    # Deleted_Clients folder
    deleted_folder_id = get_or_create_folder(
        "Deleted_Clients",
        parent_id=firm_folder_id
    )

    # Move client folder
    if client.google_drive_folder_id:

        move_folder(
            client.google_drive_folder_id,
            deleted_folder_id
        )

    db.session.delete(client)

    db.session.commit()

    flash(
        "Client deleted successfully",
        "success"
    )

    return redirect(
        url_for("clients.client_list")
    )
