import csv, io, requests, os

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
      MIG  -> read from Name; include MAINLINE, startswith int/hotfix/rel_, or contains 'feature' (all case-insensitive)
      else -> read from Branch; include only REL_YYYY_MM in current±2 (case-insensitive exact)
    """
    envnum = _get_envnum()
    key = f"streams:v1:env{envnum}:{app_name}"  # bump key version to invalidate old cache
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
    key = f"builds:v1:env{envnum}:{app_name}:{stream}"  # <-- bumped to v3
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
        return _make_test_data()

    ttl = int(current_app.config.get("APP_DATA_TTL", 900))
    key = "app_data:v1:env1"  # single key for test data

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    data = _make_test_data()
    cache.set(key, data, timeout=ttl)
    return data