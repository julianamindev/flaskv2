from flask import current_app, redirect, render_template, url_for
from flask_login import login_required
from . import bp

@bp.get("/")
def index():
    return redirect(url_for("web.home.dashboard"), code=302)

@bp.get("/home")
@bp.get("/dashboard")
@login_required
def dashboard():
    current_app.app_log.info("view_dashboard")  
    return render_template("dashboard.html")