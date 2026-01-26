"""
Shared infrastructure for the AMT Cycle Workbench backend HTTP API.

Exports:
- Config constants: OUTPUT_DIR, REFERENCE_DATA_PATH, TEMP_DIR, MATERIALS
- Status stores: export_status, import_status, sse_subscribers
- Concurrency: _status_lock, MAX_STATUS_ENTRIES
- Status accessors: get_export_status, set_export_status, get_import_status,
  set_import_status, _store_status, _notify_sse, _remove_subscriber
- HTTP helpers: json_error, file_response, HttpError
- Validation: resolve_material, validate_zone_materials, validate_export_config
- Load-zones helpers: load_zones_summary_from_des_inputs,
  load_zones_summary_from_model, pick_load_zones_summary
- DRY helpers: sse_response, serve_job_file
"""

import os
import json
import asyncio
import threading as _threading
import logging
import gzip
from typing import Dict, List
from queue import Queue, Empty

from litestar import Response
from litestar.enums import MediaType
from litestar.response import ServerSentEvent

import backend.job_store as job_store
from backend.core.db_config import (
    OUTPUT_PATH,
    REFERENCE_DATA_PATH as _REFERENCE_DATA_PATH,
    TEMP_DIR,
)
from backend.scripts.simulation_generator import (
    load_materials,
    validate_material_name,
    DEFAULT_MATERIAL,
)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Resolve paths relative to backend directory or use absolute paths
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_path(path_var, default_relative):
    """Resolve path: if relative, make it relative to backend_dir; if absolute, use as-is."""
    if os.path.isabs(path_var):
        return path_var
    return os.path.join(_backend_dir, path_var)


OUTPUT_DIR = _resolve_path(OUTPUT_PATH, "../output")
REFERENCE_DATA_PATH = _resolve_path(_REFERENCE_DATA_PATH, "../reference_data")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Materials reference data (loaded once; empty dict means validation is skipped)
MATERIALS_PATH = os.path.join(REFERENCE_DATA_PATH, "materials.json")
MATERIALS = load_materials(MATERIALS_PATH)

# ---------------------------------------------------------------------------
# Status stores
# ---------------------------------------------------------------------------

# NOTE: in-memory + single-process only — a multi-worker ASGI deployment would
# not share these. Mutated from daemon threads, so guard with a lock and bound
# the number of retained entries (M3).
_status_lock = _threading.Lock()
MAX_STATUS_ENTRIES = 256

# Store export status
export_status = {}

# Store import status (for import + export flow)
import_status = {}

# SSE event queues for real-time updates (site_name -> list of queues)
sse_subscribers: Dict[str, List[Queue]] = {}

# ---------------------------------------------------------------------------
# Job-store startup (runs once on import)
# ---------------------------------------------------------------------------

# Durable job state: back the in-memory dicts with a DuckDB file so status
# survives restart. Wrapped in try/except so a bad/locked DB degrades gracefully.
try:
    _jobs_path = os.path.join(OUTPUT_DIR, "jobs.duckdb")
    job_store.init_job_store(_jobs_path)
    export_status.update(job_store.load_all("export"))
    import_status.update(job_store.load_all("import"))
except Exception as _jse:
    logging.getLogger(__name__).warning(
        "[job_store] Startup init failed — in-memory only: %s", _jse
    )

# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def _store_status(store: dict, key: str, data: dict):
    """Thread-safe write with simple FIFO eviction to bound memory (M3)."""
    with _status_lock:
        store[key] = data
        if len(store) > MAX_STATUS_ENTRIES:
            for old_key in list(store.keys())[:-MAX_STATUS_ENTRIES]:
                store.pop(old_key, None)


def get_export_status(site_name: str) -> dict:
    """Get export status for a site."""
    with _status_lock:
        return export_status.get(
            site_name, {"status": "idle", "progress": 0, "message": "", "files": {}}
        )


def set_export_status(
    site_name: str,
    status: str,
    progress: int = 0,
    message: str = "",
    files: dict = None,
    load_zones: list = None,
):
    """Set export status for a site and notify SSE subscribers.

    `load_zones` is the export-complete discovery summary ([{id, name, hint}]).
    It rides ONLY on the API/SSE response (status payload + SSE event) and is
    never persisted into the serialized artifacts. Included only when supplied.
    """
    data = {
        "status": status,
        "progress": progress,
        "message": message,
        "files": files or {},
    }
    if load_zones is not None:
        data["load_zones"] = load_zones
    prior_status = export_status.get(site_name, {}).get("status")
    _store_status(export_status, site_name, data)
    if status != prior_status:
        job_store.persist("export", site_name, data)
    # Notify SSE subscribers
    _notify_sse(site_name, "export", data)


def get_import_status(site_name: str) -> dict:
    """Get import+export status for a site."""
    with _status_lock:
        return import_status.get(
            site_name, {"status": "idle", "progress": 0, "message": "", "files": {}}
        )


def set_import_status(
    site_name: str,
    status: str,
    progress: int = 0,
    message: str = "",
    files: dict = None,
):
    """Set import+export status for a site and notify SSE subscribers."""
    data = {
        "status": status,
        "progress": progress,
        "message": message,
        "files": files or {},
    }
    prior_status = import_status.get(site_name, {}).get("status")
    _store_status(import_status, site_name, data)
    if status != prior_status:
        job_store.persist("import", site_name, data)
    # Notify SSE subscribers
    _notify_sse(site_name, "import", data)


def _notify_sse(site_name: str, event_type: str, data: dict):
    """Push event to all SSE subscribers for a site."""
    key = f"{event_type}:{site_name}"
    print(
        f"[SSE] Notifying {key}, status={data.get('status')}, subscribers={len(sse_subscribers.get(key, []))}",
        flush=True,
    )
    if key in sse_subscribers:
        event_data = json.dumps(data)
        dead_queues = []
        for q in sse_subscribers[key]:
            try:
                q.put_nowait(event_data)
                print("[SSE] Event pushed to queue successfully", flush=True)
            except Exception as e:
                print(f"[SSE] Failed to push to queue: {e}", flush=True)
                dead_queues.append(q)
        # Remove dead queues
        for q in dead_queues:
            sse_subscribers[key].remove(q)
    else:
        print(f"[SSE] No subscribers for {key}", flush=True)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


class HttpError(Exception):
    """Carries an HTTP status + JSON body out of the synchronous import worker."""

    def __init__(self, status: int, body: dict):
        super().__init__(body.get("error", "error"))
        self.status = status
        self.body = body


def json_error(data: dict, status: int = 200) -> Response:
    """jsonify(data), status -> Litestar Response (serialized via msgspec)."""
    return Response(content=data, media_type=MediaType.JSON, status_code=status)


def file_response(file_path: str, filename: str) -> Response:
    """Read a file into memory, delete it from disk, and return it as a download."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    # Delete file after reading to optimize disk space
    try:
        os.remove(file_path)
        print(f"[Cleanup] Deleted file after reading: {filename}", flush=True)
    except Exception as e:
        print(f"[Cleanup] Failed to delete file {filename}: {e}", flush=True)

    # Determine mimetype based on file extension
    if filename.endswith(".gz"):
        mimetype = "application/gzip"
    elif filename.endswith(".xlsx"):
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        mimetype = "application/json"

    return Response(
        content=file_bytes,
        media_type=mimetype,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


def _remove_subscriber(key: str, q: Queue):
    if key in sse_subscribers and q in sse_subscribers[key]:
        sse_subscribers[key].remove(q)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def resolve_material(raw):
    """Resolve and validate a requested material before a job starts.

    Returns (material_name, error_response). A falsy/omitted value defaults to
    DEFAULT_MATERIAL (not an error). When the materials catalog is loaded, an
    unknown material yields (None, 400 response); otherwise (name, None).
    """
    material = raw or DEFAULT_MATERIAL
    if MATERIALS:
        try:
            material = validate_material_name(material, MATERIALS)
        except ValueError as e:
            return None, json_error({"error": str(e)}, 400)
    return material, None


def validate_zone_materials(raw):
    """Validate a zone_materials map's VALUES against the materials catalog.

    Returns (zone_materials_or_None, error_response). Keys are coerced to int;
    each value must be a known material name when the catalog is loaded. Unknown
    value -> (None, 400). Keys are NOT checked against detected zones (zones are
    unknown until the job runs) — an unmatched key is handled at runtime as
    warn + site default.
    """
    if not raw:
        return None, None
    if not isinstance(raw, dict):
        return None, json_error(
            {"error": "Invalid config: zone_materials must be an object"}, 400
        )
    resolved = {}
    for k, v in raw.items():
        try:
            zid = int(k)
        except TypeError, ValueError:
            return None, json_error(
                {
                    "error": f"Invalid config: zone_materials key '{k}' must be an integer zone id"
                },
                400,
            )
        if MATERIALS:
            try:
                v = validate_material_name(v, MATERIALS)
            except ValueError as e:
                return None, json_error({"error": str(e)}, 400)
        resolved[zid] = v
    return resolved, None


def validate_export_config(config: dict):
    """Validate numeric export config params that are PRESENT in the request.

    Only params supplied by the caller are checked — omitted params use defaults
    (which are always valid) and are not rejected here.

    Returns (ok: bool, error_response). On success ok=True, error_response=None.
    Mirrors the shape of resolve_material.
    """
    checks = [
        # (key, condition_fn, description)
        (
            "limit",
            lambda v: isinstance(v, int) and v > 0,
            "limit must be an integer > 0",
        ),
        (
            "sample_interval",
            lambda v: isinstance(v, int) and v > 0,
            "sample_interval must be an integer > 0",
        ),
        (
            "simplify_epsilon",
            lambda v: isinstance(v, (int, float)) and v > 0,
            "simplify_epsilon must be a number > 0",
        ),
        (
            "max_node_distance",
            lambda v: isinstance(v, (int, float)) and v > 0,
            "max_node_distance must be a number > 0",
        ),
        (
            "merge_tolerance",
            lambda v: isinstance(v, (int, float)) and v >= 0,
            "merge_tolerance must be a number >= 0",
        ),
        (
            "zone_grid_size",
            lambda v: isinstance(v, (int, float)) and v > 0,
            "zone_grid_size must be a number > 0",
        ),
        (
            "zone_min_stops",
            lambda v: isinstance(v, int) and v >= 1,
            "zone_min_stops must be an integer >= 1",
        ),
        (
            "sim_time",
            lambda v: isinstance(v, (int, float)) and v > 0,
            "sim_time must be a number > 0",
        ),
    ]
    for key, cond, msg in checks:
        if key in config:
            v = config[key]
            # bool is a subclass of int in Python (isinstance(True, int) is True),
            # so reject booleans explicitly before the numeric checks would pass
            # True/False through as 1/0.
            if isinstance(v, bool):
                return False, json_error(
                    {"error": f"Invalid config: {key} must not be a boolean"}, 400
                )
            if not cond(v):
                return False, json_error({"error": f"Invalid config: {msg}"}, 400)
    return True, None


# ---------------------------------------------------------------------------
# Load-zones summary helpers
# ---------------------------------------------------------------------------


def load_zones_summary_from_des_inputs(des_inputs_path):
    """Build the export-complete `load_zones` summary by READING the already
    written des_inputs artifact. This lives ONLY in the API/SSE response layer —
    it is never written back into any serialized artifact (model.json /
    des_inputs.json / ledger.json stay byte-identical).

    Each entry is {id, name, hint}, where hint is the zone's detected_location /
    centroid if present in the artifact, else None. Best-effort: any read/parse
    failure yields [] rather than failing the export.
    """
    if not des_inputs_path or not os.path.exists(des_inputs_path):
        return []
    try:
        if des_inputs_path.endswith(".gz"):
            with gzip.open(des_inputs_path, "rb") as f:
                des_inputs = json.loads(f.read())
        else:
            with open(des_inputs_path, "rb") as f:
                des_inputs = json.loads(f.read())
    except Exception:
        return []
    return [
        {"id": z.get("id"), "name": z.get("name"), "hint": None}
        for z in des_inputs.get("load_zones", [])
    ]


def load_zones_summary_from_model(model_path):
    """Build the export-complete `load_zones` summary from model.json.

    model.json load zones carry `detected_location: {x, y, z}` (the centroid),
    so the hint field will be non-null for every zone that has one.

    Shape: [{id, name, hint}] where hint = zone.get("detected_location") or None.
    Best-effort: any read/parse failure yields [] rather than failing the export.
    """
    if not model_path or not os.path.exists(model_path):
        return []
    try:
        with open(model_path, "r") as f:
            model = json.loads(f.read())
    except Exception:
        return []
    return [
        {
            "id": z.get("id"),
            "name": z.get("name"),
            "hint": z.get("detected_location") or None,
        }
        for z in model.get("load_zones", [])
    ]


def pick_load_zones_summary(model_path, des_inputs_path):
    """Choose the richest available source for the load-zones summary.

    Preference: model.json (carries detected_location → non-null hint) when
    present; falls back to des_inputs.json.gz (name only, hint null) when the
    model artifact was not produced (e.g. export_model=False run).
    Both absent → [].
    """
    if model_path and os.path.exists(model_path):
        return load_zones_summary_from_model(model_path)
    return load_zones_summary_from_des_inputs(des_inputs_path)


# ---------------------------------------------------------------------------
# New DRY helpers
# ---------------------------------------------------------------------------


def sse_response(event_type: str, site_name: str) -> ServerSentEvent:
    """Shared SSE stream for export/import progress. `event_type` is 'export' or
    'import'. Emits the current status immediately, then streams queue events until
    a terminal ('completed'/'error') status. Mirrors the prior per-flow generators."""
    get_status = get_export_status if event_type == "export" else get_import_status

    async def event_stream():
        q = Queue()
        key = f"{event_type}:{site_name}"
        sse_subscribers.setdefault(key, []).append(q)
        current = get_status(site_name)
        yield json.dumps(current)
        if current.get("status") in ("completed", "error"):
            _remove_subscriber(key, q)
            return
        try:
            while True:
                try:
                    data = await asyncio.to_thread(q.get, True, 1.0)
                except Empty:
                    continue
                yield data
                if json.loads(data).get("status") in ("completed", "error"):
                    break
        finally:
            _remove_subscriber(key, q)

    return ServerSentEvent(event_stream())


def serve_job_file(
    status: dict,
    file_type: str,
    valid_types: list,
    not_completed_msg: str = "Export not completed",
) -> Response:
    """Shared download handler for export/import artifacts. Validates the file type,
    that the job completed, and that the file exists, then serves + deletes it.
    Returns json_error(...) on any failure (same statuses/messages as before)."""
    if file_type not in valid_types:
        return json_error(
            {"error": f"Invalid file type. Must be one of: {valid_types}"}, 400
        )
    if status.get("status") != "completed":
        return json_error({"error": not_completed_msg}, 400)
    filename = status.get("files", {}).get(file_type)
    if not filename:
        return json_error({"error": f"File {file_type} not found"}, 404)
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return json_error({"error": "File not found on server"}, 404)
    return file_response(file_path, filename)
