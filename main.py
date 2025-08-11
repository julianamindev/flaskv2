from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from flaskv2 import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5555, debug=True)
