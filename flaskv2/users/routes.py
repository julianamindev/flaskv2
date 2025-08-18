import logging
import secrets
import string
import time
from datetime import datetime, timezone

from markupsafe import Markup
from flaskv2 import bcrypt, db, mail

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message

from flaskv2.models import User
from flaskv2.users.forms import ForgotPasswordForm, LoginForm, RegistrationForm, ResetPasswordForm
from flaskv2.utils.db import safe_commit
from flaskv2.utils.timing import add_duration

# ---- audit helper (JSON to audit.log) ---------------------------------------
def audit(action: str, **fields):
    """Standardize audit events. 'action' is the log message; fields go to JSON."""
    current_app.audit.info(action, extra=fields)
# -----------------------------------------------------------------------------

users = Blueprint('users', __name__)

@users.route("/register", methods=['GET', 'POST'])
@login_required
def register():
    start = time.perf_counter()
    current_app.app_log.info("view_register")

    if not current_user.is_admin:
        audit("access_denied", outcome="denied", reason="not_admin")
        abort(403)

    form = RegistrationForm()
    if form.validate_on_submit():
        # generate temporary password (DO NOT log it)
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        hashed_password = bcrypt.generate_password_hash(temp_password).decode('utf-8')

        user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_password,
            is_admin=form.is_admin.data,
            is_active=False
        )
        db.session.add(user)

        if not safe_commit():
            current_app.logger.error("register_db_commit_failed", extra={"target_username": form.username.data})
            audit("user_register", outcome="error", target_username=form.username.data, reason="db_commit_failed")
            flash("An internal error occurred. Please try again later.", "danger")
            return redirect(url_for('users.register'))

        # Send link with token (DO NOT log token)
        token = user.get_reset_token()
        link = url_for('users.reset_password', token=token, _external=True)

        sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_USERNAME")

        msg = Message("Set up your account password", recipients=[user.email], sender=sender)
        msg.body = f"""Hello {user.username},

Your temporary password is: {temp_password}

Please go to the following link to set your own password:
{link}

This link will expire in 1 hour.
"""

        audit(
            "register_mail_prepare",
            from_addr=sender,
            to_addr=user.email,
            server=current_app.config.get("MAIL_SERVER"),
            port=current_app.config.get("MAIL_PORT"),
            use_tls=current_app.config.get("MAIL_USE_TLS"),
            use_ssl=current_app.config.get("MAIL_USE_SSL"),
        )

        start_extra = {"target_user_id": user.id}
        try:
            with add_duration(start_extra):
                mail.send(msg)
            current_app.app_log.info("register_mail_sent", extra=start_extra)
            audit("user_register", outcome="success", target_user_id=user.id, target_username=user.username, target_email=user.email, is_admin=user.is_admin)
            flash(f"User registered. Activation email sent to {user.email}.", "success")
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            current_app.logger.exception("register_mail_send_failed", extra={"target_user_id": user.id, "duration_ms": duration_ms})
            audit("user_register", outcome="error", target_user_id=user.id, reason="mail_send_failed")
            flash("An error has occurred.", "danger")

        return redirect(url_for('users.register'))

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            current_app.app_log.warning("register_validation_failed", extra={"error": f"{field}: {errors[0]}"})
            flash(f"{field}: {errors[0]}", "danger")
            break
        return redirect(url_for('users.register'))

    return render_template('register.html', form=form)


@users.route("/forgot_password", methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    current_app.app_log.info("view_forgot_password")
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            # optional: avoid user enumeration; keep UX identical
            audit("password_reset_requested", outcome="unknown_email", email=form.email.data)
            flash("If that email exists, a reset link has been sent.", "info")
            return redirect(url_for('users.login'))

        # generate temporary password (DO NOT log it)
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        hashed_password = bcrypt.generate_password_hash(temp_password).decode('utf-8')

        user.password = hashed_password
        user.is_active = False

        if not safe_commit():
            current_app.logger.error("forgot_password_db_commit_failed", extra={"target_user_id": user.id})
            audit("password_reset_requested", outcome="error", target_user_id=user.id, reason="db_commit_failed")
            flash("An internal error occurred. Please try again later.", "danger")
            return redirect(url_for('users.forgot_password'))

        token = user.get_reset_token()
        link = url_for('users.reset_password', token=token, _external=True)

        msg = Message("Reset Password", recipients=[user.email])
        msg.body = f"""Hello {user.username},

Your temporary password is: {temp_password}

Please go to the following link to set a new password:
{link}

This link will expire in 1 hour.
"""

        start_extra = {"target_user_id": user.id}
        try:
            with add_duration(start_extra):
                mail.send(msg)
            current_app.app_log.info("register_mail_sent", extra=start_extra)
            audit("password_reset_requested", outcome="success", target_user_id=user.id, target_email=user.email)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            current_app.logger.exception("forgot_password_mail_send_failed", extra={"target_user_id": user.id, "duration_ms": duration_ms})
            audit("password_reset_requested", outcome="error", target_user_id=user.id, reason="mail_send_failed")

        flash(f"Password reset email sent to {user.email}.", "success")
        return redirect(url_for('users.login'))

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            current_app.app_log.warning("forgot_password_validation_failed", extra={"error": f"{field}: {errors[0]}"})
            flash(f"{field}: {errors[0]}", "danger")
            break
        return redirect(url_for('users.forgot_password'))

    return render_template('forgot_password.html', form=form)


@users.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    current_app.app_log.info("view_login")
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if not user:
            audit("login_attempt", outcome="failed", username=form.username.data, reason="user_not_found")
            flash("Login failed. Please check your username and password.", "danger")
            return redirect(url_for('users.login'))

        if bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user)
            session.permanent = True
            session['login_time'] = datetime.now(timezone.utc).timestamp()
            user.last_login = datetime.now(timezone.utc)

            if not safe_commit():
                current_app.logger.error("login_update_last_login_failed", extra={"user_id": user.id})
                audit("login_post_update", outcome="error", user_id=user.id, reason="db_commit_failed")
                flash("An internal error occurred. Please try again later.", "danger")
                return redirect(url_for('users.login'))

            current_app.app_log.info("login_success", extra={"user_id": user.id})
            audit("login_attempt", outcome="success", username=user.username, user_id=user.id)
            return redirect(url_for('main.home'))

        audit("login_attempt", outcome="failed", username=user.username, user_id=user.id, reason="bad_credentials")
        flash("Login failed. Please check your username and password.", "danger")
        return redirect(url_for('users.login'))

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            if field == 'csrf_token':
                current_app.app_log.info("login_csrf_invalid")
                audit("login_attempt", outcome="denied", reason="csrf_invalid")
                flash(Markup("You've been idle for too long. <a href=''>Refresh the page</a> and try again."), "info")
            else:
                current_app.app_log.warning("login_validation_failed", extra={"error": f"{field}: {errors[0]}"})
            break
        return redirect(url_for('users.login'))

    return render_template('login.html', form=form)


@users.route("/logout")
def logout():
    if current_user.is_authenticated:
        current_app.app_log.info("logout", extra={"user_id": current_user.id})
        audit("logout", outcome="success", user_id=current_user.id, username=current_user.username)
    logout_user()
    return redirect(url_for('users.login'))


@users.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if not current_user.can_delete(user):
        audit("delete_user", outcome="denied", target_user_id=user.id, target_username=user.username, reason="forbidden")
        abort(403)

    if user.id == current_user.id:
        audit("delete_user", outcome="denied", target_user_id=user.id, reason="self_delete_blocked")
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("main.user_list"))

    db.session.delete(user)
    if not safe_commit():
        current_app.logger.error("delete_user_db_commit_failed", extra={"target_user_id": user.id})
        audit("delete_user", outcome="error", target_user_id=user.id, reason="db_commit_failed")
        flash("An internal error occurred. Please try again later.", "danger")
        return redirect(url_for("main.user_list"))

    current_app.app_log.info("delete_user", extra={"target_user_id": user.id})
    audit("delete_user", outcome="success", target_user_id=user.id, target_username=user.username)
    flash(f"User '{user.username}' deleted.", "success")
    return redirect(url_for("main.user_list"))


@users.route("/grant_admin/<int:user_id>", methods=["POST"])
@login_required
def grant_admin(user_id):
    user = User.query.get_or_404(user_id)
    if not current_user.can_grant_admin(user):
        audit("grant_admin", outcome="denied", target_user_id=user.id, target_username=user.username, reason="forbidden")
        abort(403)

    user.is_admin = True
    if not safe_commit():
        current_app.logger.error("grant_admin_db_commit_failed", extra={"target_user_id": user.id})
        audit("grant_admin", outcome="error", target_user_id=user.id, reason="db_commit_failed")
        flash("An internal error occurred. Please try again later.", "danger")
        return redirect(url_for("main.user_list"))

    current_app.app_log.info("grant_admin", extra={"target_user_id": user.id})
    audit("grant_admin", outcome="success", target_user_id=user.id, target_username=user.username)
    flash(f"Granted admin privileges to {user.username}.", "success")
    return redirect(url_for("main.user_list"))


@users.route("/remove_admin/<int:user_id>", methods=["POST"])
@login_required
def remove_admin(user_id):
    user = User.query.get_or_404(user_id)
    if not current_user.can_revoke_admin(user):
        audit("revoke_admin", outcome="denied", target_user_id=user.id, target_username=user.username, reason="forbidden")
        abort(403)

    if not user.is_admin:
        audit("revoke_admin", outcome="noop", target_user_id=user.id, reason="not_admin")
        flash(f"{user.username} is not an admin.", "info")
    elif user.id == current_user.id:
        audit("revoke_admin", outcome="denied", target_user_id=user.id, reason="self_revoke_blocked")
        flash("You cannot remove admin privileges from yourself.", "warning")
    elif user.username == "root":
        audit("revoke_admin", outcome="denied", target_user_id=user.id, reason="root_protected")
        flash("You cannot remove admin privileges from the root user.", "warning")
    else:
        user.is_admin = False
        if not safe_commit():
            current_app.logger.error("revoke_admin_db_commit_failed", extra={"target_user_id": user.id})
            audit("revoke_admin", outcome="error", target_user_id=user.id, reason="db_commit_failed")
            flash("An internal error occurred. Please try again later.", "danger")
            return redirect(url_for("main.user_list"))
        current_app.app_log.info("revoke_admin", extra={"target_user_id": user.id})
        audit("revoke_admin", outcome="success", target_user_id=user.id, target_username=user.username)
        flash(f"Removed admin privileges from {user.username}.", "success")

    return redirect(url_for("main.user_list"))


@users.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    current_app.app_log.info("view_reset_password")
    user = User.verify_reset_token(token)
    if user is None:
        audit("reset_password", outcome="denied", reason="invalid_or_expired_token")
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('users.login'))

    if user.is_active:
        audit("reset_password", outcome="denied", target_user_id=user.id, reason="already_activated")
        flash('Your account is already activated.', 'warning')
        return redirect(url_for('users.login'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        if not bcrypt.check_password_hash(user.password, form.old_password.data):
            audit("reset_password", outcome="denied", target_user_id=user.id, reason="bad_temp_password")
            flash("Temporary password is incorrect.", "danger")
            return redirect(url_for('users.reset_password', token=token))

        user.password = bcrypt.generate_password_hash(form.new_password.data).decode('utf-8')
        user.is_active = True
        if not safe_commit():
            current_app.logger.error("reset_password_db_commit_failed", extra={"target_user_id": user.id})
            audit("reset_password", outcome="error", target_user_id=user.id, reason="db_commit_failed")
            flash("An internal error occurred. Please try again later.", "danger")
            return redirect(url_for('users.reset_password', token=token))

        current_app.app_log.info("reset_password_success", extra={"target_user_id": user.id})
        audit("reset_password", outcome="success", target_user_id=user.id)
        flash('Your password has been updated. You can now login.', 'success')
        return redirect(url_for('users.login'))

    elif request.method == 'POST':
        for field, errors in form.errors.items():
            current_app.app_log.warning("reset_password_validation_failed", extra={"error": f"{field}: {errors[0]}"})
            flash(f"{field}: {errors[0]}", "danger")
            break
        return redirect(url_for('users.reset_password', token=token))

    return render_template('reset_password.html', token=token, form=form)


# --- SMTP probes (TLS/SSL) -----------------------------------------------
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

def _smtp_probe(mode: str, to_addr: str):
    cfg = current_app.config
    host = cfg["MAIL_SERVER"]
    username = cfg["MAIL_USERNAME"]
    password = cfg["MAIL_PASSWORD"]
    sender = cfg.get("MAIL_DEFAULT_SENDER") or username

    ts = datetime.now(timezone.utc).isoformat()
    subject = f"SMTP {mode.upper()} probe [{ts}]"
    body = f"Hello! This is an SMTP {mode.upper()} probe from your app at {ts}.\nFrom={sender}\nTo={to_addr}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("DevOps Dashboard", sender))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid()

    try:
        if mode.lower() == "ssl":
            server = smtplib.SMTP_SSL(host, 465, timeout=20)
            server.ehlo()
        else:
            server = smtplib.SMTP(host, 587, timeout=20)
            server.ehlo()
            server.starttls()
            server.ehlo()

        # Only show SMTP conversation when debugging
        server.set_debuglevel(1 if current_app.debug else 0)

        server.login(username, password)
        refused = server.sendmail(sender, [to_addr], msg.as_string())
        server.quit()

        ok = (refused == {})
        return ok, {"refused": refused, "subject": subject}
    except smtplib.SMTPAuthenticationError as e:
        return False, {"error": "SMTPAuthenticationError", "code": e.smtp_code, "msg": (e.smtp_error or b"").decode("utf-8", "ignore")}
    except smtplib.SMTPException as e:
        return False, {"error": type(e).__name__, "msg": str(e)}
    except Exception as e:
        return False, {"error": type(e).__name__, "msg": str(e)}

@users.route("/__smtp_test")
@login_required
def smtp_test():
    mode = request.args.get("mode", "tls")  # tls | ssl
    to_addr = request.args.get("to") or current_user.email

    ok, info = _smtp_probe(mode, to_addr)
    current_app.app_log.info("smtp_probe", extra={"mode": mode, "to": to_addr, "ok": ok, **info})
    if ok:
        return f"OK ({mode}) → server accepted. Subject: {info.get('subject')}\nCheck the recipient mailbox (incl. Spam/All Mail).", 200
    else:
        return f"FAIL ({mode}) → {info}", 500
# -------------------------------------------------------------------------
