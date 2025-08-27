
import time
from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from flaskv2.models import User

from . import bp

# @login_required
@bp.route("/users_list")
def user_list():
    # if not current_user.is_admin:
    #     audit("access_denied", outcome="denied", reason="not_admin")
    #     abort(403)

    start = time.perf_counter()
    try:
        users = User.query.all()
        duration_ms = (time.perf_counter() - start) * 1000
        current_app.app_log.info("view_user_list", extra={"count": len(users), "duration_ms": round(duration_ms, 2)})
        return render_template('userlist.html', users=users)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        # Stack trace + request/user context go to errors.log (JSON)
        current_app.logger.exception("user_list_query_failed")
        # Audit trail (no secrets): who attempted, how long it took
        # audit("user_list_query_failed", outcome="error", duration_ms=round(duration_ms, 2))
        flash("Could not load users at the moment.", "warning")
        return redirect(url_for("web.home.dashboard"))