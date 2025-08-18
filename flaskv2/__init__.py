
from copy import deepcopy
import os

from flask import Flask, current_app, flash, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, current_user, logout_user
from flaskv2.config import BaseConfig
from flaskv2.logging_setup import setup_logging
from flaskv2.extensions import cache
from flask_mail import Mail

from flaskv2.utils.helpers import get_app_data, get_streams_for_app, _get_envnum
from flaskv2.utils.page_dict import side_nav_items

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'users.login'
login_manager.login_message_category = 'info'
mail = Mail()

def create_app(config_class=BaseConfig):
    app = Flask(__name__)

    app.config.from_object(config_class)

    @app.context_processor
    def inject_apps():
        return {"APPS": app.config.get("LARS_APPS", ["MIG", "HCM", "IEFin", "Landmark"])}
    
    # ---- Side nav: Section -> Subsection -> Links ----
    def build_side_nav():
        items = deepcopy(side_nav_items)

        # Role-based section pruning (remove entire "Admin" section for non-admins)
        if not getattr(current_user, "is_admin", False):
            items.pop("Admin", None)

        current_ep = request.endpoint  # e.g. 'main.lars2aws'

        # Walk: section -> subsection -> links
        for section_name, subsections in items.items():
            # subsections is a dict: { "AWS": {...}, "Another": {...} }
            for sub_name, details in subsections.items():
                is_expanded = False
                for link in details.get("child_links", []):
                    link["is_active"] = (link.get("route") == current_ep)
                    is_expanded = is_expanded or link["is_active"]
                details["is_expanded"] = is_expanded

        return items

    @app.context_processor
    def inject_side_nav():
        # available in ALL templates as `side_nav`
        return {"side_nav": build_side_nav()}

    setup_logging(app)

    os.makedirs(app.config["CACHE_DIR"], exist_ok=True)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    cache.init_app(app)

    # ---- Warmup at boot ----
    with app.app_context():
        try:
            envnum = _get_envnum()
            if envnum == 1:
                # Dev/test: warm synthetic blob used only in ENV=1
                get_app_data(force_refresh=True)
                app.app_log.info("test app_data warmed (filesystem cache primed)")
            else:
                # Staging/Prod: warm stream lists (cheap; builds stay on-demand)
                for name in app.config["LARS_APPS"]:
                    get_streams_for_app(name)
                app.app_log.info("streams warmed for %s", ", ".join(app.config["LARS_APPS"]))
        except Exception:
            app.logger.exception("warmup failed")


    # Prevent caching of all pages, including login
    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    from flaskv2.users.routes import users
    from flaskv2.main.routes import main
    from flaskv2.errors.handlers import errors
    from flaskv2.errortest.routes import test

    app.register_blueprint(users)
    app.register_blueprint(main)
    app.register_blueprint(errors)
    app.register_blueprint(test)

    return app