from app.extensions import db


class Client(db.Model):

    __tablename__ = "clients"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    firm_id = db.Column(
        db.Integer,
        db.ForeignKey("firms.id"),
        nullable=False
    )

    client_name = db.Column(
        db.String(255),
        nullable=False
    )

    mobile = db.Column(
        db.String(20)
    )

    email = db.Column(
        db.String(255)
    )

    pan_number = db.Column(
        db.String(20),
        nullable=False
    )

    aadhaar_number = db.Column(
        db.String(20)
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )
    client_type = db.Column(
    db.String(50)
)

    is_primary_personal = db.Column(
    db.Boolean,
    default=False
)
    is_active = db.Column(
    db.Boolean,
    default=True,
    nullable=False
)
    google_drive_folder_id = db.Column(
    db.String(255)
)

