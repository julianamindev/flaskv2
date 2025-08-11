from datetime import datetime, timezone
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user

from flaskv2.models import User

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


@main.route("/lars2aws")
@login_required
def lars2aws():
    current_app.app_log.info("view_lars2aws")
    return render_template('lars2aws.html')

@main.route("/list")
@login_required
def user_list():
    try:
        users = User.query.all()
        current_app.app_log.info("view_user_list", extra={"count": len(users)})
        current_app.logger.exception("user_list_query_failed")
        return render_template('userlist.html', users=users)
    except Exception:
        # Human-readable error + stack trace
        current_app.logger.error("user_list_query_failed", exc_info=True)
        # Optional audit trail of the failure (who attempted it)
        audit("user_list_query_failed", outcome="error")
        flash("Could not load users at the moment.", "warning")
        return redirect(url_for("main.home"))

@main.route("/check-session")
def check_session():
    # Routine pings are dropped by DropPathFilter; only log interesting events.
    if not current_user.is_authenticated:
        # User already logged out (browser still pinging)
        audit("session_check_unauthenticated", outcome="redirect_login", force_log=True)
        flash("Session expired. Please log in again.", "warning")
        return redirect(url_for('users.login'))
    
    login_time = session.get('login_time')
    if login_time:
        now = datetime.now(timezone.utc).timestamp()
        timeout = current_app.permanent_session_lifetime.total_seconds()
        if now - login_time > timeout:
            username = getattr(current_user, "username", "-")
            logout_user()
            session.pop('login_time', None)
            audit(
                "session_expired",
                user=username,
                reason="timeout",
                max_age_seconds=timeout,
                force_log=True  # bypass DropPathFilter for this important event
            )
            flash("Session expired. Please log in again.", "warning")
            return redirect(url_for('users.login'))

    # still valid; no log (keeps noise down)   
    return '', 204  # Session still valid


# @main.route("/__audit_test")
# def audit_test():
#     current_app.audit.info("audit_test", extra={"foo": "bar"})
#     return "ok"