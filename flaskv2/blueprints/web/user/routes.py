from datetime import datetime, timezone
from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from markupsafe import Markup

from flaskv2.blueprints.web.user.forms import LoginForm
from flaskv2.models import User
from flaskv2.utils.db import safe_commit
from flaskv2 import bcrypt
from . import bp

# ---- audit helper (JSON to audit.log) ---------------------------------------
def audit(action: str, **fields):
    """Standardize audit events. 'action' is the log message; fields go to JSON."""
    current_app.audit.info(action, extra=fields)


@bp.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('web.home.dashboard'))

    current_app.app_log.info("view_login")
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if not user:
            audit("login_attempt", outcome="failed", username=form.username.data, reason="user_not_found")
            flash("Login failed. Please check your username and password.", "danger")
            return redirect(url_for('web.user.login'))

        if bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user)
            session.permanent = True
            session['login_time'] = datetime.now(timezone.utc).timestamp()
            user.last_login = datetime.now(timezone.utc)

            if not safe_commit():
                current_app.logger.error("login_update_last_login_failed", extra={"user_id": user.id})
                audit("login_post_update", outcome="error", user_id=user.id, reason="db_commit_failed")
                flash("An internal error occurred. Please try again later.", "danger")
                return redirect(url_for('web.user.login'))

            current_app.app_log.info("login_success", extra={"user_id": user.id})
            audit("login_attempt", outcome="success", username=user.username, user_id=user.id)
            return redirect(url_for('web.home.dashboard'))

        audit("login_attempt", outcome="failed", username=user.username, user_id=user.id, reason="bad_credentials")
        flash("Login failed. Please check your username and password.", "danger")
        return redirect(url_for('web.user.login'))

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            if field == 'csrf_token':
                current_app.app_log.info("login_csrf_invalid")
                audit("login_attempt", outcome="denied", reason="csrf_invalid")
                flash(Markup("You've been idle for too long. <a href=''>Refresh the page</a> and try again."), "info")
            else:
                current_app.app_log.warning("login_validation_failed", extra={"error": f"{field}: {errors[0]}"})
            break
        return redirect(url_for('web.user.login'))

    return render_template('login.html', form=form)

@bp.route("/logout")
def logout():
    if current_user.is_authenticated:
        current_app.app_log.info("logout", extra={"user_id": current_user.id})
        audit("logout", outcome="success", user_id=current_user.id, username=current_user.username)
    logout_user()
    return redirect(url_for('web.user.login'))