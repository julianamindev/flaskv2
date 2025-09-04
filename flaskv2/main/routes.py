from collections import defaultdict, Counter
from datetime import datetime, timezone
import json
import boto3
import time
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, logout_user

from flaskv2.main.forms import BlankForm
from flaskv2.models import User
from flaskv2.utils.contants import (
    TMP_BUILDS_CLEAR_LIST,
    TMP_BUILDS_FILTER_REGEX,
    TMP_DIR
)
from flaskv2.utils.helpers import _get_envnum, _paginate, _sanitize_suffix, build_prefix_index_from_keys, get_app_data, get_builds_for_app_stream, get_object_version_meta, get_running_landmark_targets, get_stacks_summary, get_streams_for_app, list_pssc_tasks, plan_artifacts, s3_build_prefix_index, stream_exists_live, upload_item, upload_plan

from flaskv2.utils.ssm import send_inject_command, ssm_get_command_status


from botocore.exceptions import ClientError, WaiterError


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
    stacks = get_stacks_summary(region="us-east-1")

    total_stacks = len(stacks)
    state_counts = Counter(s["state"] for s in stacks)
    states = ["Running", "Off", "Opening", "Closing", "Degraded", "Unknown"]

    return render_template(
        "aws/instances.html",
        stacks=stacks,
        states=states,
        total_stacks=total_stacks,
        state_counts=state_counts,
    )

@main.route("/aws/stack/<stack_name>/storage-db-live")
@login_required
def stack_storage_db_live(stack_name: str):
    region = "us-east-1"
    ec2 = boto3.client("ec2", region_name=region)
    ssm = boto3.client("ssm", region_name=region)

    # 1) Find the DB instance id for this stack
    db_instance_id = None
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "tag:aws:cloudformation:stack-name", "Values": [stack_name]}]
    ):
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                if tags.get("aws:cloudformation:logical-id") == "INFORBCDB01Instance":
                    db_instance_id = inst["InstanceId"]

    if not db_instance_id:
        return jsonify({"stack": stack_name, "error": "DB instance not found"}), 404

    # 2) Send SSM command to run PowerShell on Windows (Get-Volume -> JSON)
    #    Output: DriveLetter, FileSystemLabel, Size, SizeRemaining
    ps_script = r"""
$vols = Get-Volume | Where-Object { $_.DriveLetter -ne $null }
$vols | Select-Object DriveLetter, FileSystemLabel,
    @{n='Size';e={[int64]$_.Size}},
    @{n='SizeRemaining';e={[int64]$_.SizeRemaining}} | ConvertTo-Json -Depth 3
""".strip()

    try:
        send_resp = ssm.send_command(
            InstanceIds=[db_instance_id],
            DocumentName="AWS-RunPowerShellScript",
            Parameters={"commands": [ps_script]},
            CloudWatchOutputConfig={"CloudWatchOutputEnabled": False},
            TimeoutSeconds=60,
        )
        command_id = send_resp["Command"]["CommandId"]
    except ClientError as e:
        return jsonify({"stack": stack_name, "error": f"SSM send failed: {e.response['Error'].get('Message', 'Unknown')}"}), 500

    # 3) Poll for command result (simple loop; ~10s max)
    status = "InProgress"
    output = None
    for _ in range(20):
        time.sleep(0.5)
        inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=db_instance_id)
        status = inv.get("Status")
        if status in ("Success", "Cancelled", "Failed", "TimedOut"):
            output = inv.get("StandardOutputContent") or ""
            error_out = inv.get("StandardErrorContent") or ""
            break

    if status != "Success":
        return jsonify({"stack": stack_name, "status": status, "error": (error_out or "Command did not succeed")}), 500

    # 4) Parse JSON -> compute used/free in GiB
    import json, math
    try:
        data = json.loads(output)
        # PowerShell returns either an object or an array
        volumes = data if isinstance(data, list) else [data]
        result = []
        for v in volumes:
            size_b = int(v.get("Size") or 0)
            free_b = int(v.get("SizeRemaining") or 0)
            used_b = max(size_b - free_b, 0)
            gib = 1024 ** 3
            result.append({
                "drive": str(v.get("DriveLetter") or "").upper(),
                "label": v.get("FileSystemLabel") or "",
                "size_gib": round(size_b / gib, 2),
                "used_gib": round(used_b / gib, 2),
                "free_gib": round(free_b / gib, 2),
            })
    except Exception as e:
        return jsonify({"stack": stack_name, "error": f"Parse failed: {e}", "raw": output}), 500

    return jsonify({
        "stack": stack_name,
        "db_instance_id": db_instance_id,
        "volumes": result,
        "note": "Live values from Get-Volume via SSM. Used=Size-SizeRemaining."
    }), 200


# @main.route("/aws/instances")
# @login_required
# def instances():
#     return render_template('aws/instances.html')

@main.route("/bastion/task-scheduler-jobs")
@login_required
def task_scheduler_list():
    current_app.app_log.info("view_task_scheduler_jobs")
    jobs = list_pssc_tasks()
    return render_template("bastion/task_scheduler_jobs.html", jobs=jobs)

# ----------

@main.route("/aws/s3_builds")
@login_required
def s3_builds():
    current_app.app_log.info("view_s3_builds")

    try:
        prefix_map = s3_build_prefix_index(bucket="migops", root="LARS/")
    except ClientError as e:
        abort(500)


    return render_template("aws/s3_builds.html", prefix_map=prefix_map)

@main.route("/api/s3/object_meta")
@login_required
def s3_object_meta():
    rel_key = (request.args.get("key") or "").strip()
    if not rel_key:
        return jsonify({"ok": False, "error": "missing key"}), 400

    data = get_object_version_meta(bucket="migops", root="LARS/", rel_key=rel_key)
    return jsonify({"ok": True, "metadata": data})

@main.route("/api/stacks")
@login_required
def api_stacks():
    state = (request.args.get("state") or "").lower()
    # Strict: a stack is "running" only if all 4 required roles are running,
    # and we return just the Landmark app instance (INFORBCLM01LInstance).
    if state == "running":
        data = get_running_landmark_targets(region="us-east-1")
        return jsonify(data)
    # Optional fallback: full summary (if you ever need it)
    data = get_stacks_summary(region="us-east-1")
    return jsonify(data)


#### INJECT ROUTES

@main.route("/api/inject", methods=["POST"])
@login_required
def api_inject():
    """
    Body JSON:
      {
        "instance_id": "i-...",
        "key_prefix": "MT/AUG/",  // "" for root (LARS/)
        "files": ["Install-LMMIG.jar", "LANDMARK.jar"]
      }
    """
    data = request.get_json(silent=True) or {}
    instance_id = (data.get("instance_id") or "").strip()
    key_prefix  = data.get("key_prefix") or ""
    files       = data.get("files") or []
    preclear    = bool(data.get("preclear", True))

    if not instance_id or not isinstance(files, list) or not all(isinstance(x, str) for x in files):
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    try:
        # If preclear=False, pass empty list; else pass None to use defaults
        preclear_names = [] if not preclear else TMP_BUILDS_CLEAR_LIST

        cmd_id = send_inject_command(
            instance_id=instance_id,
            bucket="migops",
            root="LARS/",
            key_prefix=key_prefix,
            files=files,
            region="us-east-1",
            dest=TMP_DIR,
            preclear_names=preclear_names,
            filtered_listing=True,
            list_filter_regex=TMP_BUILDS_FILTER_REGEX,
        )
        return jsonify({"ok": True, "job_id": cmd_id, "instance_id": instance_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@main.route("/api/inject/<job_id>/status")
@login_required
def api_inject_status(job_id: str):
    instance_id = (request.args.get("instance_id") or "").strip()
    if not instance_id:
        return jsonify({"ok": False, "error": "missing instance_id"}), 400
    try:
        stat = ssm_get_command_status(command_id=job_id, instance_id=instance_id, region="us-east-1")
        stat["ok"] = True
        return jsonify(stat)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500