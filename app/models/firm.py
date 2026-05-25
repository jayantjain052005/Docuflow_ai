from app.extensions import db


class Firm(db.Model):

    __tablename__ = "firms"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    firm_name = db.Column(
        db.String(255),
        nullable=False
    )

    email = db.Column(
        db.String(255)
    )

    mobile = db.Column(
        db.String(20)
    )

    drive_root_folder_id = db.Column(
        db.String(255)
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )
    users = db.relationship(
    "User",
    backref="firm",
    lazy=True
)