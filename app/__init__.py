"""
DocLedger CA Edition
Enterprise Flask App Factory
"""

import os

from flask import Flask, request
from config import Config
from app.routes.clients import clients_bp
from app.extensions import (
    db,
    bcrypt,
    jwt,
    migrate
)


def create_app():
    
    base_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    app = Flask(
        __name__,
        template_folder=os.path.join(
            base_dir,
            "app",
            "templates"
        ),
        static_folder=os.path.join(
            base_dir,
            "static"
        ),
    )

    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.documents import documents_bp
    from app.routes.search import search_bp
    from app.routes.admin import admin_bp
    from app.routes.organizations import org_bp
    from app.routes.whatsapp import whatsapp_bp
    from app.routes.sharing import sharing_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(sharing_bp)
    try:
        from app.routes.chat_routes import chat_bp
        app.register_blueprint(chat_bp)
    except ModuleNotFoundError:
        pass
    app.register_blueprint(clients_bp)
    from app.models import (
    Firm,
    User,
    Client,
    Document,
    AuditLog
)

    @app.route("/webhook", methods=["GET"])
    def verify_whatsapp_webhook():
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if verify_token == "867779121@#":
            return challenge or "", 200

        return "Verification failed", 403

    return app
