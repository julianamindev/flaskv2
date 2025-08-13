import os
from bootstrap_env import load_env
envnum = load_env()

from flaskv2 import create_app
app = create_app()

def run():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5555"))

    if envnum == 3:
        # --- Production: waitress ---
        try:
            from waitress import serve
        except ImportError as e:
            raise SystemExit(
                "ENVNUM=3 requires waitress. Install it first, e.g.:\n"
                "  uv add waitress"
            ) from e

        threads = int(os.getenv("WEB_THREADS", "8"))     # tune if needed
        backlog = int(os.getenv("WEB_BACKLOG", "2048"))  # tune if needed
        serve(app, host=host, port=port, threads=threads, backlog=backlog)
    else:
        # --- Dev/Staging: Flask dev server; reloader only for ENVNUM=1 ---
        app.run(
            host=host,
            port=port,
            debug=(envnum in [1, 2]),
            use_reloader=(envnum in [1, 2]),
        )



if __name__ == "__main__":
    run()
