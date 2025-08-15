import boto3
import csv, io, requests, os, re

from flask import current_app
from flaskv2.extensions import cache
from datetime import datetime
from dateutil.relativedelta import relativedelta  # pip install python-dateutil
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
