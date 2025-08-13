from contextlib import contextmanager
import time
from typing import Dict, MutableMapping

@contextmanager
def add_duration(extra: MutableMapping[str, object]):
    """
    Context manager that measures elapsed time and writes 'duration_ms' into the
    provided 'extra' dict, even if an exception occurs.

    Usage:
        extra = {"target_user_id": user.id}
        with add_duration(extra):
            mail.send(msg)
        current_app.app_log.info("event_name", extra=extra)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        extra["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
