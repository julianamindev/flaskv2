import json
import subprocess
from typing import Any, Dict, List, Optional
import boto3
import csv, io, requests, os, re
import shlex
from flask import current_app
from flaskv2.extensions import cache
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from collections import defaultdict

MATURITY = {
    "R":  "Released",
    "UT": "UpgradeTested",
    "ST": "SmokeTested",
    "AQ": "AppQualified",
    "B":  "Built",
    "TO": "TurnedOver",
    "JT": "JunitTested",
}

_MATURITY_NAME_TO_CODE = {v.lower(): k for k, v in MATURITY.items()}

# Reusable session with retries/timeouts
_session = requests.Session()
_adapter = HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
))
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def _fetch_csv_text(path: str) -> str:
    """
    Fetch plaintext CSV from LARS, e.g. 'MIG' or 'MIG/MAINLINE'.
    Uses config['LARS_BASE_URL'], e.g. https://builds.lawson.com/lars/util/get
    """
    base = current_app.config["LARS_BASE_URL"].rstrip("/")
    url = f"{base}/{path.strip('/')}/"
    r = _session.get(url, timeout=10)
    r.raise_for_status()
    return r.text

def _iter_csv_rows(csv_text: str):
    """
    Yield normalized dict rows from CSV.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        yield { (k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() }

def _rel_window(now: datetime | None = None, span: int = 2) -> set[str]:
    """
    Return lowercase REL_YYYY_MM values for current month ± span months.
    """
    now = now or datetime.now()
    vals = []
    for delta in range(-span, span + 1):
        d = now + relativedelta(months=delta)
        vals.append(f"REL_{d.strftime('%Y_%m')}")
    return {v.lower() for v in vals}

def get_streams_for_app(app_name: str) -> list[str]:
    """
    Streams selection:
      MIG  -> read from Name; include MAINLINE, startswith int/hotfix/rel_/feature (case-insenstive)
      else -> read from Branch; include only REL_YYYY_MM in current±2 (case-insensitive exact)
    """
    envnum = _get_envnum()
    key = f"streams:v1:env{envnum}:{app_name}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    txt = _fetch_csv_text(app_name)
    out: list[str] = []
    rel5 = _rel_window()  # lowercase set for current±2 months

    # pick the column to use
    col = "Name" if app_name == "MIG" else "Branch"

    for row in _iter_csv_rows(txt):
        val = (row.get(col) or "").strip()
        if not val:
            continue
        lo = val.lower()

        if app_name == "MIG":
            if (
                lo == "mainline"
                or lo.startswith(("int", "hotfix", "rel_", "feature"))
            ):
                out.append(val)
        else:
            if lo in rel5:
                out.append(val)

    out = sorted(set(out), key=str.lower)
    cache.set(key, out, timeout=int(current_app.config.get("LARS_STREAMS_TTL", 1800)))
    current_app.app_log.info("streams loaded: app=%s count=%s", app_name, len(out))
    return out

def get_builds_for_app_stream(app_name: str, stream: str) -> list[dict]:
    """
    Fetch /<APP>/<STREAM>/ CSV and return list of {release_id, code} dicts,
    where code is the maturity prefix (e.g., 'R', 'B', 'ST', ...).
    """
    envnum = _get_envnum()
    key = f"builds:v1:env{envnum}:{app_name}:{stream}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    txt = _fetch_csv_text(f"{app_name}/{stream}")
    items: list[dict] = []
    for row in _iter_csv_rows(txt):
        rid = (row.get("ReleaseID") or "").strip()
        mname = (row.get("Maturity.Name") or "").strip().lower()
        if rid:
            code = _MATURITY_NAME_TO_CODE.get(mname, "N")  # default 'N' if missing/unknown
            items.append({"release_id": rid, "code": code})

    ttl = int(current_app.config.get("LARS_BUILDS_TTL", 900))
    cache.set(key, items, timeout=ttl)
    current_app.app_log.info("builds loaded: app=%s stream=%s count=%s", app_name, stream, len(items))
    return items


def stream_exists_live(app_name: str, stream: str) -> bool:
    """
    Return True iff https://.../get/<app>/<stream>/ returns 2xx.
    We don't filter here—just check the live endpoint.
    """
    try:
        # Will raise for non-2xx (e.g., 404)
        _fetch_csv_text(f"{app_name}/{stream}")
        return True
    except requests.HTTPError as e:
        # 4xx/5xx → does not exist
        return False
    except Exception:
        current_app.logger.exception("stream_exists_live: unexpected error app=%s stream=%s", app_name, stream)
        return False


def _paginate(items, page: int, per_page: int):
    start = (page - 1) * per_page
    end   = start + per_page
    return items[start:end], end < len(items)

# ---------- FOR TESTS (ENVNUM = 1, 2)

def _make_test_data():
    # 4 apps, ~40 streams each, ~15 builds per stream
    data = {}
    app_names = current_app.config.get("LARS_APPS", ["MIG", "HCM", "IEFin", "Landmark"])
    for app_name in app_names:
        streams = {}
        for j in range(1, 41):           
            s_name = f"Stream {j}"
            builds = [f"{j}.{k:02d}" for k in range(1, 16)]  # 15 builds
            streams[s_name] = builds
        data[app_name] = streams
    return data

def _get_envnum():
    # Prefer config (set by your bootstrap_env) then env var, default to 1.
    try:
        return int(current_app.config.get("ENVNUM") or os.getenv("ENVNUM", 1))
    except Exception:
        return 1

def get_app_data(*, force_refresh: bool = False):
    """
    TEST-ONLY provider.
    - ENVNUM == 1  -> return cached synthetic data from _make_test_data()
    - ENVNUM in (2, 3) -> return {} (routes use on-demand helpers in real envs)
    """
    envnum = _get_envnum()
    if envnum != 1:
        return {}

    ttl = int(current_app.config.get("APP_DATA_TTL", 900))
    key = "app_data:v1:env1"  # single key for test data

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    data = _make_test_data()
    cache.set(key, data, timeout=ttl)
    return data

# ----------------- S3 + Upload helpers -----------------

from boto3.s3.transfer import TransferConfig

# Separate session for uploads if you want; using the same _session is also fine.
if "_uploader_session" not in globals():
    _uploader_session = requests.Session()

def _s3_client():
    # AWS creds resolved by your staging setup (env/role)
    return boto3.client("s3", region_name=current_app.config.get("AWS_REGION"))

def _s3_transfer_config():
    chunk_mb = int(current_app.config.get("S3_MULTIPART_CHUNK_MB", 16))
    return TransferConfig(
        multipart_threshold=chunk_mb * 1024 * 1024,
        multipart_chunksize=chunk_mb * 1024 * 1024,
        max_concurrency=int(current_app.config.get("S3_MAX_CONCURRENCY", 4)),
        use_threads=True,
    )

def _sanitize_suffix(suffix: str) -> str:
    """
    Ensure the S3 prefix is always under 'LARS/', with a trailing slash.
    UI supplies only the suffix; 'LARS/' root is enforced here.
    """
    base = "LARS/"
    suffix = (suffix or "").strip()
    suffix = suffix.lstrip("/").rstrip("/")
    return base if not suffix else f"{base}{suffix}/"

def _content_type_for(name: str) -> str | None:
    if name.endswith(".jar"):
        return "application/java-archive"
    if name.endswith(".txt"):
        return "text/plain"
    return None

def _get_grid_installer_version_any(any_base: str) -> str | None:
    """
    any_base like: https://.../Landmark/<stream>/<build>/Any
    Fetch pom.properties under grid-installer.jar and parse version=...
    """
    url = (
        any_base.rstrip("/")
        + "/grid-installer.jar/META-INF/maven/grid.runtime/installer-code/pom.properties"
    )
    try:
        r = _uploader_session.get(url, timeout=30)
        r.raise_for_status()
        for line in r.text.splitlines():
            if line.startswith("version="):
                return line.split("=", 1)[1].strip()
    except Exception:
        current_app.logger.exception("grid pom.properties fetch failed: %s", url)
    return None

def _stream_to_s3_from_url(url: str, bucket: str, key: str, *, metadata: dict | None = None):
    """
    Stream the LARS artifact directly to S3 (no temp files).
    """
    s3 = _s3_client()
    extra = {}
    if metadata:
        extra["Metadata"] = metadata

    # Optional SSE from config if you use it
    sse = current_app.config.get("S3_SSE")
    if sse:
        extra["ServerSideEncryption"] = sse  # 'AES256' or 'aws:kms'
        kms = current_app.config.get("S3_KMS_KEY_ID")
        if sse == "aws:kms" and kms:
            extra["SSEKMSKeyId"] = kms

    ctype = _content_type_for(key)
    if ctype:
        extra["ContentType"] = ctype

    with _uploader_session.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        s3.upload_fileobj(
            Fileobj=resp.raw,
            Bucket=bucket,
            Key=key,
            ExtraArgs=extra,
            Config=_s3_transfer_config(),
        )

def plan_artifacts(app_name: str, stream: str, build_version: str, *, suffix_prefix: str) -> list[dict]:
    """
    Build the upload plan per your rules, FLAT into:
      s3://<bucket>/LARS/<suffix>/
    Filenames:
      MIG -> MIG_scripts.jar, Install-LMMIG.jar
      HCM -> Install-LMHCM.jar
      IEFin -> Install-LMIEFIN.jar
      Landmark -> LANDMARK.jar, grid-installer.jar, mt_dependencies.txt
    Metadata:
      - Install-LMMIG/HCM/IEFIN: {'version': <build>}
      - grid-installer.jar: {'version': <grid_version from pom.properties>}
      - Others: no metadata
    """
    bucket = current_app.config.get("S3_BUCKET", "migops")

    # Enforce 'LARS/<suffix>/' as the only prefix
    base_prefix = _sanitize_suffix(suffix_prefix)  # e.g. 'LARS/flaskv2_test/'
    s3_dir = base_prefix  # <-- FLAT: no app/stream/build subfolders

    base_landmark = current_app.config.get("LARS_BASE_URL", "https://builds.lawson.com/lars/util/get").rstrip("/")

    plan: list[dict] = []

    if app_name in ("MIG", "HCM", "IEFin"):
        # Source: /<app>/<stream>/<build>/Landmark/
        src_base = f"{base_landmark}/{app_name}/{stream}/{build_version}/Landmark"

        if app_name == "MIG":
            plan.append({
                "source_url": f"{src_base}/scripts.jar",
                "bucket": bucket,
                "key": f"{s3_dir}MIG_scripts.jar",          # renamed
                "metadata": None,
            })
            plan.append({
                "source_url": f"{src_base}/Install-LMMIG.jar",
                "bucket": bucket,
                "key": f"{s3_dir}Install-LMMIG.jar",
                "metadata": {"version": build_version},
            })

        elif app_name == "HCM":
            plan.append({
                "source_url": f"{src_base}/Install-LMHCM.jar",
                "bucket": bucket,
                "key": f"{s3_dir}Install-LMHCM.jar",
                "metadata": {"version": build_version},
            })

        elif app_name == "IEFin":
            plan.append({
                "source_url": f"{src_base}/Install-LMIEFIN.jar",
                "bucket": bucket,
                "key": f"{s3_dir}Install-LMIEFIN.jar",
                "metadata": {"version": build_version},
            })

    elif app_name == "Landmark":
        # Source: /Landmark/<stream>/<build>/Any/
        any_base = f"{base_landmark}/Landmark/{stream}/{build_version}/Any"

        plan.append({
            "source_url": f"{any_base}/LANDMARK.jar",
            "bucket": bucket,
            "key": f"{s3_dir}LANDMARK.jar",
            "metadata": {"version": build_version},
        })
        grid_ver = _get_grid_installer_version_any(any_base)
        plan.append({
            "source_url": f"{any_base}/grid-installer.jar",
            "bucket": bucket,
            "key": f"{s3_dir}grid-installer.jar",
            "metadata": ({"version": grid_ver} if grid_ver else None),
        })
        plan.append({
            "source_url": f"{any_base}/mt_dependencies.txt",
            "bucket": bucket,
            "key": f"{s3_dir}mt_dependencies.txt",
            "metadata": None,
        })

    return plan


def upload_plan(plan: list[dict]) -> list[dict]:
    """
    Execute uploads; return [{source_url, bucket, key, ok, error?}]
    """
    results = []
    for item in plan:
        url = item["source_url"]
        bucket = item["bucket"]
        key = item["key"]
        try:
            _stream_to_s3_from_url(url, bucket, key, metadata=item.get("metadata"))
            results.append({"source_url": url, "bucket": bucket, "key": key, "ok": True})
        except Exception as e:
            current_app.logger.exception("upload failed: %s -> s3://%s/%s", url, bucket, key)
            results.append({"source_url": url, "bucket": bucket, "key": key, "ok": False, "error": str(e)})
    return results

def upload_item(item: dict) -> dict:
    """
    Upload exactly one artifact.
    item: {"source_url": str, "bucket": str, "key": str, "metadata": dict|None}
    Returns: {"ok": bool, "source_url":..., "bucket":..., "key":..., "error"?: str}
    """
    url = item.get("source_url")
    bucket = item.get("bucket")
    key = item.get("key")
    meta = item.get("metadata")
    if not url or not bucket or not key:
      return {"ok": False, "error": "missing source_url/bucket/key", "source_url": url, "bucket": bucket, "key": key}
    try:
        _stream_to_s3_from_url(url, bucket, key, metadata=meta)
        return {"ok": True, "source_url": url, "bucket": bucket, "key": key}
    except Exception as e:
        current_app.logger.exception("upload failed: %s -> s3://%s/%s", url, bucket, key)
        return {"ok": False, "source_url": url, "bucket": bucket, "key": key, "error": str(e)}

# -------------------------------------------------------

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def _find_powershell():
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidates = [
        os.path.join(system_root, r"Sysnative\WindowsPowerShell\v1.0\powershell.exe"),
        os.path.join(system_root, r"System32\WindowsPowerShell\v1.0\powershell.exe"),
        "powershell.exe",
    ]
    for p in candidates:
        if p == "powershell.exe" or os.path.exists(p):
            return p
    return "powershell.exe"

PS_EXE = _find_powershell()

def _get_ps1_path():
    local = os.path.join(current_app.root_path, "ps1_scripts", "fetch_jobs.ps1")
    return local


def _run_ps1_and_parse(prefix="PSSC-"):
    ps1 = _get_ps1_path()
    if not ps1:
        current_app.logger.warning("ps1_not_found")
        return None

    cmd = [
        PS_EXE, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", ps1, "-Prefix", prefix,
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        data = json.loads(raw.decode("utf-8", "replace") or "[]")
        if isinstance(data, dict):
            data = [data]
        return data
    except subprocess.CalledProcessError as e:
        # current_app.logger.warning("ps1_failed",
        #     extra={"rc": e.returncode, "out": (e.output or b'').decode("utf-8","replace")})
        # return None
        err = (e.output or b"").decode("utf-8", "replace")
        current_app.logger.exception("ps1_failed rc=%s out=%s", e.returncode, err)
        return None
    except Exception as e:
        current_app.logger.warning("ps1_failed", extra={"err": str(e)})
        return None

def list_pssc_tasks():
    ps_rows = _run_ps1_and_parse(prefix="PSSC-")
    if ps_rows:
        rows = []
        for r in ps_rows:
            name_full = (r.get("Name") or "")
            name_no_prefix = r.get("NameNoPrefix") or (name_full[5:] if name_full.startswith("PSSC-") else name_full)
            rows.append({
                "name": name_no_prefix,
                "schedule": r.get("Regularity") or "—",
                "state": r.get("State") or "—",
                "next_run": r.get("NextRun") or "—",
                "last_run": r.get("LastRun") or "—",
                "success": r.get("Success"),
                # "last_result": str(r.get("LastTaskResult") if r.get("LastTaskResult") is not None else ""),
            })
        rows.sort(key=lambda x: x["name"].lower())
        return rows

    # CSV fallback here
    return _schtasks_csv()

def _schtasks_csv():
    """Fallback: schtasks CSV (/v). Shape + labels match fetch_jobs.ps1 output."""
    def _first(d, *names):
        for n in names:
            v = d.get(n)
            if isinstance(v, str):
                v = v.strip()
            if v:
                return v
        return ""

    def _parse_result(code_str: str | None) -> int | None:
        if not code_str:
            return None
        s = code_str.strip()
        try:
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        except Exception:
            return None

    try:
        raw = subprocess.check_output(
            ["schtasks", "/query", "/fo", "CSV", "/v"],
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.CalledProcessError as e:
        current_app.logger.error(
            "schtasks_query_failed",
            extra={"returncode": e.returncode, "output": e.output.decode(errors="replace")}
        )
        return []

    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []

    for r in reader:
        task_name = _first(r, "TaskName", "Task Name")
        if not task_name.startswith(r"\PSSC-"):
            continue

        display    = task_name.lstrip("\\")
        no_prefix  = display[5:] if display.startswith("PSSC-") else display
        schedule   = _first(r, "Schedule", "Schedule Type")

        # Normalize state similar to your PS output
        state_raw  = _first(r, "Status", "Scheduled Task State")
        if state_raw:
            sr = state_raw.strip().lower()
            if sr.startswith("ready"):
                state = "Ready"
            elif sr.startswith("disabled"):
                state = "Disabled"
            elif sr.startswith("running"):
                state = "Running"
            else:
                state = state_raw
        else:
            state = "Unknown"

        next_run   = _first(r, "Next Run Time")
        last_run   = _first(r, "Last Run Time")
        last_res_s = _first(r, "Last Result")
        code       = _parse_result(last_res_s)

        # Match your fetch_jobs.ps1 semantics
        never_run  = (not last_run) or last_run.upper() == "N/A" or code == 0x41303
        if never_run:
            success = "not yet run"
        elif code == 0:
            success = "success"
        elif code is None:
            success = "unknown"
        else:
            success = "failed"

        rows.append({
            "name": no_prefix,
            "schedule": schedule or "—",
            "state": state or "—",
            "next_run": next_run or "—",
            "last_run": last_run or "—",
            "success": success,  # string label, not boolean
            # "last_result": last_res_s or "",  # keep if you need to show raw code later
        })

    rows.sort(key=lambda x: x["name"].lower())
    return rows


# ------- S3 builds page

def s3_build_prefix_index(bucket: str = "migops", root: str = "LARS/") -> Dict[str, List[str]]:
    """
    Returns a map like:
      {
        "LARS/": ["cloud.jar"],
        "MT/": ["foo.jar"],                       # files directly under a first-level prefix
        "MT/AUG/": ["sample1.txt", "dir/x.jar"], # all files under a subprefix (recursive)
        "FEATURE/feature1/": ["build1.jar", ...],
        ...
      }
    Scans only within LARS/: root, first-level prefixes, and their subprefixes.
    """
    s3 = boto3.client("s3")
    out: Dict[str, List[str]] = defaultdict(list)
    paginator = s3.get_paginator("list_objects_v2")

    # --- 1) Root (LARS/): gather files and collect first-level prefixes ---
    first_level_prefixes = set()

    for page in paginator.paginate(Bucket=bucket, Prefix=root, Delimiter="/"):
        # Files directly under LARS/
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(root):]  # e.g., "cloud.jar"
            if rel and not rel.endswith("/"):
                out["LARS/"].append(rel)

        # First-level prefixes: e.g., "LARS/MT/", "LARS/FEATURE/", but not filtered
        for cp in page.get("CommonPrefixes", []):
            first_level_prefixes.add(cp["Prefix"])

    # --- 2) For each first-level prefix: files directly under it, and subprefixes ---
    for cat_prefix in sorted(first_level_prefixes):            # e.g., "LARS/MT/"
        cat_name = cat_prefix[len(root):].strip("/")           # -> "MT"
        sub_prefixes = set()

        # Files directly under category (-> "MT/")
        for page in paginator.paginate(Bucket=bucket, Prefix=cat_prefix, Delimiter="/"):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(cat_prefix):]             # e.g., "foo.jar"
                if rel and not rel.endswith("/"):
                    out[f"{cat_name}/"].append(rel)

            # Collect subprefixes (-> "LARS/MT/AUG/", ...)
            for cp in page.get("CommonPrefixes", []):
                sub_prefixes.add(cp["Prefix"])

        # --- 3) For each subprefix: gather ALL files under it (recursive) ---
        for sub_prefix in sorted(sub_prefixes):                # e.g., "LARS/MT/AUG/"
            sub_name = sub_prefix[len(cat_prefix):].strip("/") # -> "AUG"
            for page in paginator.paginate(Bucket=bucket, Prefix=sub_prefix):
                for obj in page.get("Contents", []):
                    rel = obj["Key"][len(sub_prefix):]         # path under the subprefix
                    if rel and not rel.endswith("/"):
                        out[f"{cat_name}/{sub_name}/"].append(rel)

    # Stable ordering for nicer UI
    return {k: sorted(v) for k, v in out.items()}


# test
def build_prefix_index_from_keys(keys: list[str]) -> dict[str, list[str]]:
    """
    Keys like:
      migops/LARS/MT/AUG/sample1.txt
      migops/LARS/FEATURE/feature1/feature2.txt
      migops/LARS/toproot.jar
      migops/LARS/MAINLINE/trunk/builds/build-1.jar
    Returns:
      {
        "LARS/": ["toproot.jar"],
        "MT/AUG/": ["sample1.txt", ...],
        "FEATURE/feature1/": ["feature2.txt", ...],
        "MAINLINE/trunk/": ["builds/build-1.jar"],
        ...
      }
    """
    base = "migops/LARS/"
    out: dict[str, list[str]] = defaultdict(list)

    for k in keys:
        if not k.startswith(base):
            continue

        raw_suffix = k[len(base):]              # keep raw to detect folder markers
        if not raw_suffix or raw_suffix.endswith("/"):
            # skip folder marker objects like ".../"
            continue

        suffix = raw_suffix.strip("/")
        parts = suffix.split("/")

        if len(parts) == 1:
            # file directly under LARS/
            out["LARS/"].append(parts[0])
            continue

        category = parts[0]

        if len(parts) == 2:
            # file directly under a category folder (e.g., MT/foo.jar)
            out[f"{category}/"].append(parts[1])
            continue

        # files under category/sub/... -> group by first two segments
        sub = parts[1]
        filename = "/".join(parts[2:])
        out[f"{category}/{sub}/"].append(filename)

    return dict(out)

TARGET_META_FILES = {
    "Install-LMMIG.jar",
    "Install-LMIEFIN.jar",
    "Install-LMHCM.jar",
    "LANDMARK.jar",
    "grid-installer.jar",
}

def get_object_version_meta(bucket: str, root: str, rel_key: str) -> Optional[Dict[str, Any]]:
    """
    Return {'version': '<value>'} if the object has version set.
    Only attempts for TARGET_META_FILES; returns None otherwise.
    rel_key is relative to `root` (e.g., 'MT/AUG/Install-LMMIG.jar').
    """
    basename = os.path.basename(rel_key)
    if basename not in TARGET_META_FILES:
        return None

    s3 = boto3.client("s3")
    full_key = f"{root}{rel_key}"
    try:
        resp = s3.head_object(Bucket=bucket, Key=full_key)
    except Exception:
        return None

    # boto3 lowercases user-metadata keys
    meta = resp.get("Metadata") or {}
    ver = meta.get("version")
    return {"version": ver} if ver else None

# -------- AWS INSTANCES

# Single place to classify a stack given its instance states
def classify_stack(states: List[str]) -> str:
    if not states:
        return "Unknown"
    all_running = all(s == "running" for s in states)
    all_stopped = all(s == "stopped" for s in states)
    opening = (any(s == "pending" for s in states) or any(s == "running" for s in states)) and any(s == "stopped" for s in states)
    closing = any(s == "stopping" for s in states)
    if all_running:
        return "Running"
    if all_stopped:
        return "Off"
    if opening and not closing:
        return "Opening"
    if closing and not opening:
        return "Closing"
    return "Degraded"


REQUIRED_ROLES = {
    "INFORBCLM01LInstance",
    "INFORBCVP01Instance",
    "INFORBCDB01Instance",
    "INFORBCAD01Instance",
}

def _collect_stack_info(*, region: str = "us-east-1") -> Dict[str, Dict[str, Any]]:
    ec2 = boto3.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_instances")

    stacks: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "states": [],
            "client": None,
            "alwayson": "Off",
            "instance_ids": [],
            "running_ids": [],
            "lm_candidate_id": None,
            "env": None,
            "region": region,
            # NEW: per-logical-id instance id and state
            "roles": {},             # {"INFORBCLM01LInstance": {"id": "...", "state": "running"}}
        }
    )

    for page in paginator.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                stack = tags.get("aws:cloudformation:stack-name")
                if not stack:
                    continue

                state = (inst.get("State") or {}).get("Name", "")
                iid = inst.get("InstanceId")
                logical_id = tags.get("aws:cloudformation:logical-id", "")

                info = stacks[stack]
                info["states"].append(state)
                if iid:
                    info["instance_ids"].append(iid)
                    if state == "running":
                        info["running_ids"].append(iid)

                if logical_id:
                    info["roles"][logical_id] = {"id": iid, "state": state}

                client = tags.get("customerPrefix")
                if client:
                    info["client"] = client

                env = tags.get("Environment") or tags.get("ENV") or tags.get("Env")
                if env:
                    info["env"] = env

                if logical_id == "INFORBCLM01LInstance":
                    info["lm_candidate_id"] = iid
                    itops_region = (tags.get("ITOPS_Region") or "").strip().upper()
                    info["alwayson"] = "On" if itops_region == "ALWAYSON" else "Off"

    return stacks

def is_stack_fully_running(info: Dict[str, Any]) -> bool:
    roles = info.get("roles", {})
    for rid in REQUIRED_ROLES:
        r = roles.get(rid)
        if not r or r.get("state") != "running":
            return False
    return True

def get_running_landmark_targets(*, region: str = "us-east-1") -> List[Dict[str, Any]]:
    stacks = _collect_stack_info(region=region)
    targets: List[Dict[str, Any]] = []
    for name, info in stacks.items():
        if not is_stack_fully_running(info):
            continue
        # Use the Landmark app instance as the target
        lm = info["roles"].get("INFORBCLM01LInstance")
        if not lm or not lm.get("id"):
            continue
        targets.append({
            "id": lm["id"],
            "name": name,
            "env": info.get("env") or "",
            "region": info.get("region"),
        })
    targets.sort(key=lambda x: x["name"])
    return targets


def get_stacks_summary(*, region: str = "us-east-1") -> List[Dict[str, Any]]:
    """
    Return a list of stacks for the Instances page, with computed state.
    Shape matches what your template already expects.
    """
    stacks = _collect_stack_info(region=region)
    out: List[Dict[str, Any]] = []
    for name, info in sorted(stacks.items()):
        out.append(
            {
                "name": name,
                "client": info.get("client") or "-",
                "state": classify_stack(info.get("states", [])),
                "alwayson": info.get("alwayson", "Off"),
            }
        )
    return out
