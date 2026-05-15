from app.routes.auth import auth_bp
from app.routes.documents import documents_bp
from app.routes.search import search_bp
 
from app.routes.admin import admin_bp
from app.routes.organizations import org_bp

__all__ = ["auth_bp", "documents_bp", "search_bp", "sharing_bp", "admin_bp", "org_bp"]
