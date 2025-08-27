from flask import Blueprint, flash, redirect, url_for
from flask_login import current_user
bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="templates")


@bp.before_request
def _require_admin_web():
    if not getattr(current_user, "is_authenticated", False):
        flash("Please log in to access this page.", "warning")
        return redirect(url_for("web.user.login"))
    if not getattr(current_user, "is_admin", False):
        flash("Admins only.", "danger")
    # Adjust target as needed; this assumes you have web.home.dashboard
    return redirect(url_for("web.home.dashboard"))

from . import routes

