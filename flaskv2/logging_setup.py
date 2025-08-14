import json, logging, logging.config
from pathlib import Path
from flask import has_request_context, request
import re

# --- Filters ---------------------------------------------------------------

class StripAnsiFilter(logging.Filter):
    _ansi = re.compile(r"\x1b\[[0-9;]*m")
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self._ansi.sub("", record.msg)
        return True


class DropPathFilter(logging.Filter):
    """Drop very noisy request paths from app/audit logs."""
    DROP_PREFIXES = ("/check-session", "/static/")
    def filter(self, record):
        if getattr(record, "force_log", False):
            return True
        if getattr(record, "name", "") == "audit":
            return True
        path = getattr(record, "path", "")
        return not any(path.startswith(p) for p in self.DROP_PREFIXES)


class RequestContextFilter(logging.Filter):
    """Attach request/user context + use the route template instead of raw path."""
    def filter(self, record):
        record.user = "-"
        record.actor_id = None
        record.ip = "-"
        record.method = "-"
        record.path = "-"
        record.endpoint = "-"

        if has_request_context():
            xff = request.headers.get("X-Forwarded-For")
            record.ip = (xff.split(",")[0].strip() if xff else request.remote_addr) or "-"
            record.method = request.method or "-"
            rule = getattr(getattr(request, "url_rule", None), "rule", None)
            record.path = rule or request.path or "-"
            record.endpoint = getattr(request, "endpoint", "-") or "-"

            # Pull from flask_login if available; never let this raise
            try:
                from flask_login import current_user  # imported here to avoid hard dep
                if getattr(current_user, "is_authenticated", False):
                    record.user = (
                        getattr(current_user, "username", None)
                        or getattr(current_user, "email", None)
                        or "-"
                    )
                    record.actor_id = getattr(current_user, "id", None)
            except Exception:
                pass
        return True


class RedactSecretsFilter(logging.Filter):
    """
    Defense-in-depth: redact secrets that might slip into messages/paths.
    - /reset_password/<token> → /reset_password/<token>
    - JWT-like strings → <jwt>
    - Query-string secrets (?token=, ?code=, ?key=, ?password=, ?secret=) → <redacted>
    """
    import re as _re
    _jwt = _re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")
    _reset_path = _re.compile(r"(/reset_password/)[A-Za-z0-9._-]+")
    _qs_secret = _re.compile(r"([?&](?:token|code|key|password|secret)=[^&]+)", _re.I)

    @classmethod
    def _redact(cls, s: str) -> str:
        if not isinstance(s, str):
            return s
        s = cls._reset_path.sub(r"\1<token>", s)
        s = cls._jwt.sub("<jwt>", s)
        s = cls._qs_secret.sub(lambda m: m.group(0).split("=")[0] + "=<redacted>", s)
        return s

    def filter(self, record: logging.LogRecord) -> bool:
        for attr in ("msg", "message", "path"):
            val = getattr(record, attr, None)
            if isinstance(val, str):
                setattr(record, attr, self._redact(val))
        return True


# --- Setup ----------------------------------------------------------------

def setup_logging(app):
    """
    Load logging.json, wire filters, and override filenames/levels/rotation
    from app.config. Keeps app.logger intact and exposes convenience loggers.
    """
    # Defaults (can be overridden by Config)
    app.config.setdefault("LOG_DIR", r"C:\logs")
    app.config.setdefault("APP_LOG_FILE",   str(Path(app.config["LOG_DIR"]) / "app.log"))
    app.config.setdefault("AUDIT_LOG_FILE", str(Path(app.config["LOG_DIR"]) / "audit.log"))
    app.config.setdefault("ERROR_LOG_FILE", str(Path(app.config["LOG_DIR"]) / "errors.log"))

    # Rotation defaults
    app.config.setdefault("APP_LOG_MAX_BYTES",   5 * 1024 * 1024)
    app.config.setdefault("APP_LOG_BACKUP_COUNT", 5)
    app.config.setdefault("AUDIT_LOG_MAX_BYTES", 5 * 1024 * 1024)
    app.config.setdefault("AUDIT_LOG_BACKUP_COUNT", 10)
    app.config.setdefault("ERROR_LOG_MAX_BYTES", 10 * 1024 * 1024)
    app.config.setdefault("ERROR_LOG_BACKUP_COUNT", 10)

    # Levels
    app.config.setdefault("ROOT_LOG_LEVEL", "WARNING")
    app.config.setdefault("APP_LOG_LEVEL", "INFO")
    app.config.setdefault("AUDIT_LOG_LEVEL", "INFO")
    app.config.setdefault("WERKZEUG_LOG_LEVEL", "WARNING")
    app.config.setdefault("SQLALCHEMY_ENGINE_LOG_LEVEL", "WARNING")

    Path(app.config["LOG_DIR"]).mkdir(parents=True, exist_ok=True)

    cfg_path = Path(app.root_path) / "logging.json"  # lives under flaskv2/
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Ensure filter import paths match this module (safe even if already set)
    for key, cls in {
        "request_context": "flaskv2.logging_setup.RequestContextFilter",
        "strip_ansi":      "flaskv2.logging_setup.StripAnsiFilter",
        "drop_noise":      "flaskv2.logging_setup.DropPathFilter",
        "redact_secrets":  "flaskv2.logging_setup.RedactSecretsFilter",
    }.items():
        if "filters" in cfg and key in cfg["filters"]:
            cfg["filters"][key]["()"] = cls

    # Override filenames and rotation from app config
    handlers = cfg.get("handlers", {})
    if "app_file" in handlers:
        handlers["app_file"]["filename"] = app.config["APP_LOG_FILE"]
        handlers["app_file"]["maxBytes"] = int(app.config["APP_LOG_MAX_BYTES"])
        handlers["app_file"]["backupCount"] = int(app.config["APP_LOG_BACKUP_COUNT"])
    if "audit_file" in handlers:
        handlers["audit_file"]["filename"] = app.config["AUDIT_LOG_FILE"]
        handlers["audit_file"]["maxBytes"] = int(app.config["AUDIT_LOG_MAX_BYTES"])
        handlers["audit_file"]["backupCount"] = int(app.config["AUDIT_LOG_BACKUP_COUNT"])
    if "errors_file" in handlers:
        handlers["errors_file"]["filename"] = app.config["ERROR_LOG_FILE"]
        handlers["errors_file"]["maxBytes"] = int(app.config["ERROR_LOG_MAX_BYTES"])
        handlers["errors_file"]["backupCount"] = int(app.config["ERROR_LOG_BACKUP_COUNT"])

    # Override logger levels from app config
    if "root" in cfg:
        cfg["root"]["level"] = app.config["ROOT_LOG_LEVEL"]
    if "loggers" in cfg:
        if "app" in cfg["loggers"]:
            cfg["loggers"]["app"]["level"] = app.config["APP_LOG_LEVEL"]
        if "audit" in cfg["loggers"]:
            cfg["loggers"]["audit"]["level"] = app.config["AUDIT_LOG_LEVEL"]
        if "werkzeug" in cfg["loggers"]:
            cfg["loggers"]["werkzeug"]["level"] = app.config["WERKZEUG_LOG_LEVEL"]
        if "sqlalchemy.engine" in cfg["loggers"]:
            cfg["loggers"]["sqlalchemy.engine"]["level"] = app.config["SQLALCHEMY_ENGINE_LOG_LEVEL"]

    logging.config.dictConfig(cfg)

    # Convenience loggers
    app.app_log = logging.getLogger("app")
    app.audit   = logging.getLogger("audit")

    # --- always capture unhandled exceptions (even in DEBUG) ----
    @app.teardown_request
    def _log_unhandled_exception(exc):
        # exc is None for normal requests; non-None for unhandled exceptions
        if exc is not None:
            # force_log bypasses DropPathFilter; exc_info tuple gives full stacktrace
            app.logger.error(
                "uncaught_exception",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"force_log": True},
            )
