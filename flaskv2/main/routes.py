from datetime import datetime, timezone
import time
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user

from flaskv2.main.forms import BlankForm
from flaskv2.models import User
from flaskv2.utils.helpers import _paginate, get_app_data, get_builds_for_app_stream, get_streams_for_app

main = Blueprint('main', __name__)

def audit(action: str, **fields):
    """Standardize audit events. 'action' becomes the log message; fields go to JSON."""
    # Use 'force_log' for events you want to keep even if path is in DropPathFilter
    current_app.audit.info(action, extra=fields)

@main.route("/")
@main.route("/home")
@login_required
def home():
    current_app.app_log.info("view_dashboard")
    return render_template('dashboard.html')


@main.route("/lars2aws", methods=["GET"])
@login_required
def lars2aws():
    APPS = current_app.config["LARS_APPS"]
    current_app.app_log.info("view_lars2aws")
    form=BlankForm()
    return render_template('lars2aws.html', form=form, apps=APPS)

# ---------- AJAX for Select2 (Streams) ----------
@main.get("/api/streams")
@login_required
def api_streams():
    app_name = request.args.get("app", "")
    q        = (request.args.get("q") or "").strip().lower()
    page     = int(request.args.get("page", 1))
    per_page = 30

    streams = get_streams_for_app(app_name)
    if q:
        streams = [s for s in streams if q in s.lower()]
    page_items, more = _paginate(streams, page, per_page)

    # Select2 expects id/text
    results = [{"id": s, "text": s} for s in page_items]
    return jsonify({"results": results, "pagination": {"more": more}})

# ---------- AJAX for Select2 (Builds) ----------
@main.get("/api/builds")
@login_required
def api_builds():
    app_name  = request.args.get("app", "")
    stream_id = request.args.get("stream_id") or request.args.get("stream") or ""
    q         = (request.args.get("q") or "").strip().lower()
    page      = int(request.args.get("page", 1))
    per_page  = 30

    builds = get_builds_for_app_stream(app_name, stream_id)
    if q:
        builds = [b for b in builds if q in b.lower()]
    page_items, more = _paginate(builds, page, per_page)

    results = [{"id": b, "text": b} for b in page_items]
    return jsonify({"results": results, "pagination": {"more": more}})

@main.route("/list")
@login_required
def user_list():
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
        audit("user_list_query_failed", outcome="error", duration_ms=round(duration_ms, 2))
        flash("Could not load users at the moment.", "warning")
        return redirect(url_for("main.home"))

@main.route("/check-session")
def check_session():
    if not current_user.is_authenticated:
        audit("session_check_unauthenticated", outcome="redirect_login", force_log=True)
        flash("Session expired. Please log in again.", "warning")
        return redirect(url_for('users.login'))

    login_time = session.get('login_time')
    if login_time:
        now = datetime.now(timezone.utc).timestamp()
        timeout = current_app.permanent_session_lifetime.total_seconds()
        age = now - login_time
        if age > timeout:
            username = getattr(current_user, "username", "-")
            logout_user()
            session.pop('login_time', None)
            audit(
                "session_expired",
                reason="timeout",
                max_age_seconds=timeout,
                session_age_seconds=round(age, 2),
                force_log=True
            )
            flash("Session expired. Please log in again.", "warning")
            return redirect(url_for('users.login'))

    return '', 204  # still valid; no noise


# @main.route("/__audit_test")
# def audit_test():
#     current_app.audit.info("audit_test", extra={"foo": "bar"})
#     return "ok"