from flask import Blueprint, jsonify, url_for
from flask_login import current_user

bp = Blueprint("admin", __name__, url_prefix="/admin")

@bp.before_request
def _require_admin_api():
    if not getattr(current_user, "is_authenticated", False):
        return jsonify(error="unauthenticated", redirect=url_for("web.user.login")), 401
    if not getattr(current_user, "is_admin", False):
        return jsonify(error="forbidden", message="Admin access required"), 403
    
from . import routes