from datetime import datetime, timezone
import time
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user

from flaskv2.main.forms import BlankForm
from flaskv2.models import User
from flaskv2.utils.helpers import _get_envnum, _paginate, _sanitize_suffix, get_app_data, get_builds_for_app_stream, get_streams_for_app, list_pssc_tasks, plan_artifacts, stream_exists_live, upload_item, upload_plan


main = Blueprint('main', __name__)

def audit(action: str, **fields):
    """Standardize audit events. 'action' becomes the log message; fields go to JSON."""
    # Use 'force_log' for events you want to keep even if path is in DropPathFilter
    current_app.audit.info(action, extra=fields)

def _selected_from_form(form):
    """Extract selected streams/builds from the summary inputs."""
    selected = {}
    apps = current_app.config.get("LARS_APPS", ["MIG", "HCM", "IEFIN", "Landmark"])
    for app in apps:
        key = app.lower()
        s = (form.get(f"summary_{key}_stream") or "").strip()
        b = (form.get(f"summary_{key}_build") or "").strip()
        if s or b:
            selected[app] = {"stream": s, "build": b}
    return selected

@main.route("/")
def index():
    return redirect(url_for("main.home"), code=302)

@main.route("/home")
@login_required
def home():
    current_app.app_log.info("view_dashboard")  
    return render_template("dashboard.html")


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

    if _get_envnum() == 1:
        # DEV: serve from test data blob
        app_data = get_app_data()
        streams = list((app_data.get(app_name) or {}).keys())
    else:
        # STG/PRD: fetch from LARS (cached)
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

    if not app_name or not stream_id:
        return jsonify({"results": [], "pagination": {"more": False}}), 400

    if _get_envnum() == 1:
        # DEV: test blob (simple strings). We still add release_id for convenience.
        app_data = get_app_data()
        builds = list((app_data.get(app_name, {}).get(stream_id, [])))
        if q:
            builds = [b for b in builds if q in b.lower()]
        page_items, more = _paginate(builds, page, per_page)
        results = [
            {"id": b, "text": b, "maturity": None, "release_id": b}
            for b in page_items
        ]
    else:
        # STG/PRD: live LARS (dicts with release_id + code)
        all_items = get_builds_for_app_stream(app_name, stream_id)
        if q:
            all_items = [it for it in all_items if q in it["release_id"].lower()]
        page_items, more = _paginate(all_items, page, per_page)
        # id = release_id; text kept for backwards-compat
        results = [
            {
                "id": it["release_id"],
                "text": f"{it['code']}--{it['release_id']}",
                "maturity": it["code"],             # e.g., 'R', 'B', 'ST', ...
                "release_id": it["release_id"],
            }
            for it in page_items
        ]

    return jsonify({"results": results, "pagination": {"more": more}})


@main.get("/api/streams/exists")
@login_required
def api_stream_exists():
    app_name = request.args.get("app", "")
    stream   = (request.args.get("stream") or "").strip()

    if not app_name or not stream:
        return jsonify({"exists": False, "error": "missing app/stream"}), 400

    # Live existence check against LARS; no filtering here
    exists = stream_exists_live(app_name, stream)
    return jsonify({"exists": exists, "stream": stream if exists else None})

@main.route("/list")
@login_required
def user_list():
    if not current_user.is_admin:
        audit("access_denied", outcome="denied", reason="not_admin")
        abort(403)

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


# @main.post("/lars2aws/upload")
# @login_required
# def lars2aws_upload():
#     """
#     Upload selected artifacts from LARS to S3.
#     Expects form POST with:
#       - summary_<app>_stream
#       - summary_<app>_build
#       - migops_lars_suffix  (UI suffix after 'LARS/')
#     Returns JSON with per-file results.
#     """
#     apps = current_app.config.get("LARS_APPS", ["MIG", "HCM", "IEFin", "Landmark"])
#     suffix = (request.form.get("migops_lars_suffix") or "").strip()
#     # Hard-enforce LARS/ root in helper; suffix may be blank -> 'LARS/'
#     all_results = []
#     any_selected = False

#     for app_name in apps:
#         s = request.form.get(f"summary_{app_name.lower()}_stream") or ""
#         b = request.form.get(f"summary_{app_name.lower()}_build") or ""
#         s, b = s.strip(), b.strip()
#         if not s or not b:
#             continue
#         any_selected = True

#         # Build plan and upload
#         plan = plan_artifacts(app_name, s, b, suffix_prefix=suffix)
#         current_app.app_log.info(
#             "upload plan: user=%s app=%s stream=%s build=%s count=%d",
#             getattr(getattr(request, "user", None), "username", "-"),
#             app_name, s, b, len(plan)
#         )
#         results = upload_plan(plan)
#         all_results.extend([{"app": app_name, "stream": s, "build": b, **r} for r in results])

#     if not any_selected:
#         return jsonify({"ok": False, "message": "No app selections found.", "results": []}), 400

#     ok = all(r.get("ok") for r in all_results) if all_results else False
#     return jsonify({"ok": ok, "results": all_results})

@main.post("/lars2aws/plan")
@login_required
def lars2aws_plan():
    """
    Build the flattened upload plan using current form selections.
    Responds with: { ok, s3_prefix, artifacts: [{app, stream, build, source_url, bucket, key, metadata?}] }
    """
    apps = current_app.config.get("LARS_APPS", ["MIG", "HCM", "IEFin", "Landmark"])
    suffix = (request.form.get("migops_lars_suffix") or "").strip()
    s3_prefix = f"s3://{current_app.config.get('S3_BUCKET','migops')}/{_sanitize_suffix(suffix)}"

    artifacts = []
    any_selected = False
    for app_name in apps:
        s = (request.form.get(f"summary_{app_name.lower()}_stream") or "").strip()
        b = (request.form.get(f"summary_{app_name.lower()}_build") or "").strip()
        if not s or not b:
            continue
        any_selected = True
        plan = plan_artifacts(app_name, s, b, suffix_prefix=suffix)
        for it in plan:
            artifacts.append({
                "app": app_name,
                "stream": s,
                "build": b,
                **it,  # source_url, bucket, key, metadata
            })

    if not any_selected:
        return jsonify({"ok": False, "message": "No app selections found.", "artifacts": []}), 400
    
    # Audit one line per submission (includes who, ip, etc. via filters)
    audit(
        "lars2aws.plan",
        s3_prefix=s3_prefix,
        artifacts_count=len(artifacts),
        selected=_selected_from_form(request.form),
    )
    
    current_app.app_log.info(
        "lars2aws.plan",
        extra={"s3_prefix": s3_prefix, "artifacts_count": len(artifacts)}
)

    return jsonify({"ok": True, "s3_prefix": s3_prefix, "artifacts": artifacts})

@main.post("/lars2aws/upload-item")
@login_required
def lars2aws_upload_item():
    """
    Upload a single artifact (JSON body).
    Requires: {source_url, bucket, key, metadata?}
    """
    data = request.get_json(silent=True) or {}
    result = upload_item(data)

    log_extra = {
        "source_url": data.get("source_url"),
        "bucket": data.get("bucket"),
        "key": data.get("key"),
        "metadata": data.get("metadata"),
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
    }

    # Write to audit log (persisted in audit.log)
    if result.get("ok"):
        audit("lars2aws.upload_item.ok", **log_extra)
    else:
        audit("lars2aws.upload_item.fail", **log_extra)

    if result.get("ok"):
        current_app.app_log.info("lars2aws.upload_item.ok", extra=log_extra)
    else:
        current_app.app_log.warning("lars2aws.upload_item.fail", extra=log_extra)

    return jsonify(result), (200 if result.get("ok") else 502)

@main.route("/aws/instances")
@login_required
def instances():
    return render_template('aws/instances.html')

@main.route("/bastion/task-scheduler-jobs")
@login_required
def task_scheduler_list():
    print(f"{current_app.root_path}")
    jobs = list_pssc_tasks()
    return render_template("bastion/task_scheduler_jobs.html", jobs=jobs)