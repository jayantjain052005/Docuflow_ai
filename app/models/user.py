from app.extensions import db, bcrypt


class User(db.Model):

    __tablename__ = "users"

    ROLE_SUPER_ADMIN = "super_admin"
    ROLE_FIRM_ADMIN = "firm_admin"
    ROLE_STAFF = "staff"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    firm_id = db.Column(
        db.Integer,
        db.ForeignKey("firms.id"),
        nullable=False
    )

    full_name = db.Column(
        db.String(255),
        nullable=False
    )

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    mobile = db.Column(
        db.String(20)
    )

    password_hash = db.Column(
        db.Text,
        nullable=False
    )

    role = db.Column(
        db.String(50),
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # Password Hashing
    def set_password(self, password):

        self.password_hash = (
            bcrypt.generate_password_hash(password)
            .decode("utf-8")
        )

    def check_password(self, password):

        return bcrypt.check_password_hash(
            self.password_hash,
            password
        )