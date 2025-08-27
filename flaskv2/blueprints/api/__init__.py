from flask import Blueprint
api = Blueprint("api", __name__, url_prefix="api")

from .v1 import v1
v1.register_blueprint(v1)