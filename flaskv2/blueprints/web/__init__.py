from flask import Blueprint

web = Blueprint("web", __name__)

from .home import bp as home_bp
from .user import bp as user_bp

web.register_blueprint(home_bp)
web.register_blueprint(user_bp)

