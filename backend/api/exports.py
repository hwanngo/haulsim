"""
ExportController — resource-oriented export endpoints at /api/exports.

Moved verbatim from app.py (export_files, process_export, get_export_status_endpoint,
export_events_sse, download_file). Only changes:
  - Route paths are controller-relative (Controller.path = "/api/exports")
  - POST 202 response gains Location header
  - Aliased call-sites (_json, _resolve_material, etc.) renamed to the jobs.py names
"""

import threading
import time
from typing import Annotated, Any, Dict, Optional

from litestar import Controller, Response, get, post
from litestar.enums import MediaType
from litestar.params import Parameter
from litestar.response import ServerSentEvent

import backend.obs as obs
from backend.scripts.simulation_generator import (
    get_connection,
    fetch_machines,
    process_site,
    load_machine_templates,
    load_machines_list,
    DEFAULT_CONFIG,
    DEFAULT_MATERIAL,
)
from backend.api.jobs import (
    OUTPUT_DIR,
    REFERENCE_DATA_PATH,
    set_export_status,
    get_export_status,
    resolve_material,
    validate_export_config,
    validate_zone_materials,
    json_error,
    sse_response,
    serve_job_file,
    pick_load_zones_summary,
)
import os

# Machine templates path
MACHINE_TEMPLATES_PATH = os.path.join(
    REFERENCE_DATA_PATH, "simulation", "machine_templates.json"
)

# Machines list path (contains machine specs by model name)
MACHINES_LIST_PATH = os.path.join(REFERENCE_DATA_PATH, "machines.json")

_EXPORT_FILE_TYPES = ["model", "des_inputs", "ledger", "routes_excel"]


def process_export(
    site_name: str,
    limit: int,
    sample_interval: int,
    grid_size: float,
    min_density: int,
    simplify_epsilon: float,
    max_node_distance: float,
    merge_tolerance: float,
    zone_grid_size: float,
    zone_min_stops: int,
    sim_time: int,
    export_model: bool = True,
    export_simulation: bool = True,
    export_routes_excel: bool = False,
    material: str = DEFAULT_MATERIAL,
    zone_materials: Optional[Dict[int, str]] = None,
):
    """Process export in background thread."""
    obs.metrics.incr("export_count")
    obs.log_event("export_start", site=site_name, job="export", stage="start")
    _t0 = time.time()
    try:
        set_export_status(site_name, "processing", 0, "Connecting to database...")

        connection = get_connection()
        if not connection:
            set_export_status(site_name, "error", 0, "Failed to connect to database")
            obs.metrics.incr("export_failures")
            obs.log_event(
                "export_error",
                site=site_name,
                job="export",
                stage="db_connect",
                error="Failed to connect to database",
            )
            return

        try:
            # H3: context-managed cursor so it always closes.
            with connection.cursor() as cursor:
                # Fetch machines
                set_export_status(
                    site_name, "processing", 10, "Fetching machine information..."
                )
                machines = fetch_machines(cursor, site_name)

                if not machines:
                    set_export_status(
                        site_name,
                        "error",
                        0,
                        f"No machines found for site: {site_name}",
                    )
                    obs.metrics.incr("export_failures")
                    obs.log_event(
                        "export_error",
                        site=site_name,
                        job="export",
                        stage="fetch_machines",
                        error="No machines found",
                    )
                    return

                # Load machine templates and machines list
                machine_templates = load_machine_templates(MACHINE_TEMPLATES_PATH)
                machines_list = load_machines_list(MACHINES_LIST_PATH)

                # Process site
                set_export_status(
                    site_name, "processing", 20, "Processing site data..."
                )
                result = process_site(
                    cursor=cursor,
                    site_name=site_name,
                    machines=machines,
                    output_dir=OUTPUT_DIR,
                    limit=limit,
                    sample_interval=sample_interval,
                    grid_size=grid_size,
                    min_density=min_density,
                    simplify_epsilon=simplify_epsilon,
                    max_node_distance=max_node_distance,
                    merge_tolerance=merge_tolerance,
                    zone_grid_size=zone_grid_size,
                    zone_min_stops=zone_min_stops,
                    sim_time=sim_time,
                    machine_templates=machine_templates,
                    machines_list=machines_list,
                    export_model=export_model,
                    export_simulation=export_simulation,
                    export_routes_excel=export_routes_excel,
                    material=material,
                    zone_materials=zone_materials,
                )

                _duration_ms = (time.time() - _t0) * 1000
                obs.metrics.observe("export_duration_last", _duration_ms)

                if result:
                    # Convert absolute paths to relative filenames
                    files = {}
                    for key, path in result.items():
                        if os.path.exists(path):
                            files[key] = os.path.basename(path)

                    # Surface detected load zones to the frontend. Prefer model.json
                    # (carries detected_location → non-null hint); fall back to
                    # des_inputs.json.gz when model was not produced (export_model=False).
                    # Read-only: NOT serialized back into any artifact (G binding).
                    load_zones_summary = pick_load_zones_summary(
                        result.get("model"),
                        result.get("des_inputs"),
                    )

                    set_export_status(
                        site_name,
                        "completed",
                        100,
                        "Export completed successfully",
                        files,
                        load_zones=load_zones_summary,
                    )
                    obs.log_event(
                        "export_complete",
                        site=site_name,
                        job="export",
                        stage="done",
                        duration_ms=_duration_ms,
                    )
                else:
                    set_export_status(site_name, "error", 0, "Failed to generate files")
                    obs.metrics.incr("export_failures")
                    obs.log_event(
                        "export_error",
                        site=site_name,
                        job="export",
                        stage="process_site",
                        error="No result returned",
                        duration_ms=_duration_ms,
                    )

        finally:
            connection.close()

    except Exception as e:
        _duration_ms = (time.time() - _t0) * 1000
        obs.metrics.incr("export_failures")
        obs.metrics.observe("export_duration_last", _duration_ms)
        obs.log_event(
            "export_error",
            site=site_name,
            job="export",
            stage="exception",
            error=str(e),
            duration_ms=_duration_ms,
        )
        set_export_status(site_name, "error", 0, f"Error: {str(e)}")


class ExportController(Controller):
    path = "/api/exports"

    @post()
    async def create(self, data: Dict[str, Any]) -> Response:
        """Export model/simulation files for a site."""
        try:
            site_name = data.get("site_name")

            if not site_name:
                return json_error({"error": "site_name is required"}, 400)

            # Check if export is already in progress
            status = get_export_status(site_name)
            if status["status"] == "processing":
                return json_error(
                    {"error": "Export already in progress", "status": status}, 409
                )

            # Get configuration from request or use defaults
            config = data.get("config", {})
            limit = config.get("limit", DEFAULT_CONFIG["data_fetching"]["limit"])
            sample_interval = config.get(
                "sample_interval", DEFAULT_CONFIG["data_fetching"]["sample_interval"]
            )
            grid_size = config.get(
                "grid_size", DEFAULT_CONFIG["road_detection"]["grid_size"]
            )
            min_density = config.get(
                "min_density", DEFAULT_CONFIG["road_detection"]["min_density"]
            )
            simplify_epsilon = config.get(
                "simplify_epsilon", DEFAULT_CONFIG["road_detection"]["simplify_epsilon"]
            )
            max_node_distance = config.get(
                "max_node_distance",
                DEFAULT_CONFIG["road_detection"]["max_node_distance"],
            )
            merge_tolerance = config.get(
                "merge_tolerance", DEFAULT_CONFIG["road_detection"]["merge_tolerance"]
            )
            zone_grid_size = config.get(
                "zone_grid_size", DEFAULT_CONFIG["zone_detection"]["grid_size"]
            )
            zone_min_stops = config.get(
                "zone_min_stops", DEFAULT_CONFIG["zone_detection"]["min_stop_count"]
            )
            sim_time = config.get("sim_time", DEFAULT_CONFIG["simulation"]["sim_time"])

            # Get export file type options (default both to True)
            export_model = data.get("export_model", True)
            export_simulation = data.get("export_simulation", True)
            export_routes_excel = data.get("export_routes_excel", False)

            # At least one type must be selected
            if not export_model and not export_simulation and not export_routes_excel:
                return json_error(
                    {"error": "At least one export type must be selected"}, 400
                )

            # Validate material name before starting the background job (Task 4).
            material, material_err = resolve_material((config or {}).get("material"))
            if material_err:
                return material_err

            # Validate per-zone material VALUES before starting the background job (G).
            # KEYS are not checked here (load zones unknown until detection runs).
            zone_materials, zm_err = validate_zone_materials(
                (config or {}).get("zone_materials")
            )
            if zm_err is not None:
                return zm_err

            # Validate numeric config params before starting the background job (C-f2).
            _, config_err = validate_export_config(config or {})
            if config_err is not None:
                return config_err

            # Start export in background thread
            thread = threading.Thread(
                target=process_export,
                args=(
                    site_name,
                    limit,
                    sample_interval,
                    grid_size,
                    min_density,
                    simplify_epsilon,
                    max_node_distance,
                    merge_tolerance,
                    zone_grid_size,
                    zone_min_stops,
                    sim_time,
                    export_model,
                    export_simulation,
                    export_routes_excel,
                    material,
                    zone_materials,
                ),
            )
            # Set "processing" SYNCHRONOUSLY before returning 202, so a same-site
            # re-export overwrites any stale "completed" status from a prior run.
            # Otherwise the SSE stream's first frame (which yields the current status
            # on connect) would replay the previous run's "completed" + old files,
            # and the frontend would render a false completion for the new job.
            set_export_status(site_name, "processing", 0, "Export queued...")

            thread.daemon = True
            thread.start()

            return Response(
                content={"message": "Export started", "site_name": site_name},
                media_type=MediaType.JSON,
                status_code=202,
                headers={"Location": f"/api/exports/{site_name}"},
            )

        except Exception as e:
            return json_error({"error": str(e)}, 500)

    @get("/{site_name:str}")
    async def state(self, site_name: Annotated[str, Parameter()]) -> Response:
        """Get export status for a site."""
        return json_error(get_export_status(site_name), 200)

    @get("/{site_name:str}/events")
    async def events(self, site_name: Annotated[str, Parameter()]) -> ServerSentEvent:
        """SSE endpoint for real-time export status updates."""
        return sse_response("export", site_name)

    @get("/{site_name:str}/files/{file_type:str}")
    async def files(
        self,
        site_name: Annotated[str, Parameter()],
        file_type: Annotated[str, Parameter()],
    ) -> Response:
        """Download exported file."""
        return serve_job_file(
            get_export_status(site_name), file_type, _EXPORT_FILE_TYPES
        )
