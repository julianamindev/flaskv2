from flask import Blueprint, current_app

test = Blueprint("test", __name__)

# 1) UNHANDLED exception (Werkzeug/Flask will log it)
@test.get("/_boom")
def boom():
    return 1 / 0  # ZeroDivisionError → 500 + stack trace in errors.log

# 2) HANDLED + explicitly logged exception
@test.get("/_boom_logged")
def boom_logged():
    try:
        {}["missing"]  # KeyError
    except Exception:
        # Will include exc_info in errors.log (json_exc formatter)
        current_app.logger.exception("test_boom_logged")
        return "logged KeyError (check errors.log)", 500