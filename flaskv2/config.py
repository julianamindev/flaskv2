import os
from datetime import timedelta
from pathlib import Path

def env_bool(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

class BaseConfig:
    # --- Core ---
    SECRET_KEY                      = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI         = os.getenv("SQLALCHEMY_DATABASE_URI")
    SQLALCHEMY_TRACK_MODIFICATIONS  = env_bool("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    PERMANENT_SESSION_LIFETIME      = timedelta(hours=3)

    # --- Mail ---
    MAIL_SERVER             = os.getenv("MAIL_SERVER")
    MAIL_PORT               = env_int("MAIL_PORT", 587)
    MAIL_USE_TLS            = env_bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL            = env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME           = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD           = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER     = os.getenv("MAIL_DEFAULT_SENDER") or MAIL_USERNAME

    # --- Logging (used by setup_logging) ---
    LOG_DIR                 = os.getenv("LOG_DIR", r"C:\logs")
    APP_LOG_FILE            = os.getenv("APP_LOG_FILE",   str(Path(LOG_DIR) / "app.log"))
    AUDIT_LOG_FILE          = os.getenv("AUDIT_LOG_FILE", str(Path(LOG_DIR) / "audit.log"))
    ERROR_LOG_FILE          = os.getenv("ERROR_LOG_FILE", str(Path(LOG_DIR) / "errors.log"))

    # levels
    ROOT_LOG_LEVEL              = os.getenv("ROOT_LOG_LEVEL", "WARNING")
    APP_LOG_LEVEL               = os.getenv("APP_LOG_LEVEL", "INFO")
    AUDIT_LOG_LEVEL             = os.getenv("AUDIT_LOG_LEVEL", "INFO")
    WERKZEUG_LOG_LEVEL          = os.getenv("WERKZEUG_LOG_LEVEL", "WARNING")
    SQLALCHEMY_ENGINE_LOG_LEVEL = os.getenv("SQLALCHEMY_ENGINE_LOG_LEVEL", "WARNING")

    # rotation
    APP_LOG_MAX_BYTES       = int(os.getenv("APP_LOG_MAX_BYTES", 5 * 1024 * 1024))
    APP_LOG_BACKUP_COUNT    = int(os.getenv("APP_LOG_BACKUP_COUNT", 5))
    AUDIT_LOG_MAX_BYTES     = int(os.getenv("AUDIT_LOG_MAX_BYTES", 5 * 1024 * 1024))
    AUDIT_LOG_BACKUP_COUNT  = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", 10))
    ERROR_LOG_MAX_BYTES     = int(os.getenv("ERROR_LOG_MAX_BYTES", 10 * 1024 * 1024))
    ERROR_LOG_BACKUP_COUNT  = int(os.getenv("ERROR_LOG_BACKUP_COUNT", 10))

# class DevConfig(BaseConfig):
#     DEBUG = True
#     ROOT_LOG_LEVEL = "INFO"      # see framework warnings in dev
#     WERKZEUG_LOG_LEVEL = "INFO"  # show requests in console


# class ProdConfig(BaseConfig):
#     DEBUG = False
#     # Keep defaults (quieter). Make sure SECRET_KEY/Mail creds come from env.


# class TestConfig(BaseConfig):
#     TESTING = True
#     # Use an in-memory or dedicated test DB if you like:
#     SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "mysql+mysqlconnector://root:root@localhost/pssc_cp_db")
