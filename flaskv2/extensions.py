from flask_bcrypt import Bcrypt
from flask_caching import Cache
from flask_login import LoginManager
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy

# Extension singletons
bcrypt = Bcrypt()
cache = Cache()
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

def init_extensions(app) -> None:
    """
    Bind all extensions to the given app instance and apply per-extension config.
    """
    db.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    cache.init_app(app)

    # Flask Login config
    login_manager.init_app(app)
    login_manager.login_view = 'users.login'
    login_manager.login_message_category = 'info'



