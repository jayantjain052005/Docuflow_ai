from app.extensions import db


class Document(db.Model):

    __tablename__ = "documents"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    firm_id = db.Column(
        db.Integer,
        db.ForeignKey("firms.id"),
        nullable=False
    )

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id")
    )

    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    filename = db.Column(
        db.String(255),
        nullable=False
    )

    document_type = db.Column(
        db.String(100)
    )

    assessment_year = db.Column(
        db.String(20)
    )

    confidence_score = db.Column(
        db.Float
    )

    status = db.Column(
        db.String(50),
        default="pending_review"
    )

    extracted_text = db.Column(
        db.Text
    )

    extracted_json = db.Column(
        db.JSON
    )

    google_drive_file_id = db.Column(
        db.String(255)
    )

    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )