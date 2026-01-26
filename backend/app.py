"""
Litestar API for AMT Cycle Workbench WebApp (served by granian).
"""

import os
import sys

from litestar import Litestar
from litestar.config.cors import CORSConfig
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the repo root to sys.path so `backend.*` is importable when app.py is
# run directly (e.g. `uv run python -c "import app"` from the backend dir).
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_webapp_root = os.path.dirname(_backend_dir)
if _webapp_root not in sys.path:
    sys.path.insert(0, _webapp_root)

from backend.api.exports import ExportController
from backend.api.imports import ImportController
from backend.api.system import SystemController

# Restrict CORS to the known frontend origin(s) (M1). Override with CORS_ORIGINS
# (comma-separated) for other dev setups; defaults to the React dev server.
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]


app = Litestar(
    route_handlers=[ExportController, ImportController, SystemController],
    cors_config=CORSConfig(allow_origins=_cors_origins),
)


if __name__ == "__main__":
    # Dev entrypoint: serve the ASGI app with granian. Bind to localhost by default;
    # override HOST/PORT via env. Production uses `granian` on the CLI (see Dockerfile).
    from granian import Granian
    from granian.constants import Interfaces

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5001))
    Granian(
        "app:app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
    ).serve()
