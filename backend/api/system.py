"""
SystemController — stateless read endpoints for the AMT Cycle Workbench API.

Endpoints (public paths unchanged):
- GET /api/materials  - List available materials
- GET /api/sites      - List available sites
- GET /api/health     - Health check
- GET /api/metrics    - In-memory process metrics snapshot
"""

from litestar import Controller, Response, get

from backend.api.jobs import MATERIALS, json_error
import backend.obs as obs
from backend.scripts.simulation_generator import get_connection, fetch_sites


class SystemController(Controller):
    path = "/api"

    @get("/materials")
    async def materials(self) -> Response:
        """Get list of available materials derived from the module-level MATERIALS catalog."""
        mats = MATERIALS.get("materials", []) if MATERIALS else []
        return json_error(
            {
                "materials": [
                    {
                        "name": m["name"],
                        "display_name": m.get("display_name", m["name"]),
                    }
                    for m in mats
                ]
            }
        )

    @get("/sites")
    async def sites(self) -> Response:
        """Get list of available sites."""
        try:
            connection = get_connection()
            if not connection:
                return json_error({"error": "Failed to connect to database"}, 500)

            try:
                # H3: context-managed cursor so it always closes.
                with connection.cursor() as cursor:
                    sites = fetch_sites(cursor)
                return json_error({"sites": sites}, 200)
            finally:
                connection.close()
        except Exception as e:
            return json_error({"error": str(e)}, 500)

    @get("/health")
    async def health(self) -> Response:
        """Health check endpoint."""
        return json_error({"status": "ok"}, 200)

    @get("/metrics")
    async def metrics(self) -> Response:
        """Return a read-only snapshot of in-memory process metrics (JSON)."""
        return json_error(obs.metrics.snapshot(), 200)
