from flask import Blueprint
v1 = Blueprint("v1", __name__, url_prefix="/v1")

from .admin import bp as admin_bp

v1.register_blueprint(admin_bp)