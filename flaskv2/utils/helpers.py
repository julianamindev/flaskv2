import os

from flask import current_app
from flaskv2.extensions import cache

def _paginate(items, page: int, per_page: int):
    start = (page - 1) * per_page
    end   = start + per_page
    return items[start:end], end < len(items)

# ---------- FOR TESTS (ENVNUM = 1, 2)

def _make_test_data():
    # 4 apps, ~40 streams each, ~15 builds per stream
    data = {}
    app_names = ["MIG", "HCM", "IEFIN", "Landmark"]
    for app_name in app_names:
        streams = {}
        for j in range(1, 41):           
            s_name = f"Stream {j}"
            builds = [f"{j}.{k:02d}" for k in range(1, 16)]  # 15 builds
            streams[s_name] = builds
        data[app_name] = streams
    return data

def _fetch_lars_data():
    """
    TODO: Implement your real fetch here (ENVNUM=2/3).
    Must return the same shape:
      { APP_NAME: { STREAM_NAME: [BUILD1, BUILD2, ...] } }
    """
    # Example skeleton:
    # data = {"MIG": {}, "HCM": {}, "IEFIN": {}, "Landmark": {}}
    # ... populate from upstream ...
    # return data
    return _make_test_data()  # temporary: reuse test generator while wiring

def _get_envnum():
    # Prefer config (set by your bootstrap_env) then env var, default to 1.
    try:
        return int(current_app.config.get("ENVNUM") or os.getenv("ENVNUM", 1))
    except Exception:
        return 1

def get_app_data(*, force_refresh: bool = False):
    """
    Env-aware, cached provider of app data.
    ENVNUM=1 -> _make_test_data()
    ENVNUM=2/3 -> _fetch_lars_data()
    Stored via Flask-Caching (FileSystemCache), TTL from APP_DATA_TTL (seconds).
    """

    envnum = _get_envnum()
    ttl    = int(current_app.config.get("APP_DATA_TTL", 900))
    key    = f"app_data:v1:env{envnum}"

    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    source = _make_test_data if envnum == 1 else _fetch_lars_data

    try:
        data = source()
    except Exception:
        current_app.logger.exception("app_data_refresh_failed")
        # fall back to last good cache if any
        fallback = cache.get(key)
        if fallback is not None:
            return fallback
        raise  # first load must succeed

    cache.set(key, data, timeout=ttl)
    return data