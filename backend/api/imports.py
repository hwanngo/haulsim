"""
ImportController — resource-oriented import endpoints at /api/imports.

Moved verbatim from app.py (process_import_and_export, _extract_and_parse,
import_files, get_import_status_endpoint, import_events_sse,
download_imported_file). Only changes:
  - Route paths are controller-relative (Controller.path = "/api/imports")
  - POST 202 response gains Location header
  - Aliased call-sites (_json, _HttpError, _file_response, _resolve_material)
    renamed to the jobs.py names (json_error, HttpError, file_response,
    resolve_material)
"""

import os
import shutil
import tempfile
import threading
import zipfile
from typing import Annotated, Any, Dict, List

from litestar import Controller, Request, Response, get, post
from litestar.enums import MediaType
from litestar.params import Parameter
from litestar.response import ServerSentEvent
from tqdm import tqdm
from werkzeug.utils import secure_filename

import backend.obs as obs
from backend.core.db_config import EXECUTE_FILE_PATH as _EXECUTE_FILE_PATH
from backend.core.gateway_parser_wrapper import parse_gateway_files
from backend.core.gateway_data_converter import (
    process_parser_output,
    convert_imported_records_to_telemetry,
    extract_zones_from_import,
)
from backend.scripts.simulation_generator import (
    get_connection,
    load_machine_templates,
    load_machines_list,
    process_site,
    DEFAULT_CONFIG,
    DEFAULT_MATERIAL,
)
from backend.api.jobs import (
    OUTPUT_DIR,
    TEMP_DIR,
    set_import_status,
    get_import_status,
    json_error,
    file_response,
    HttpError,
    resolve_material,
    sse_response,
    serve_job_file,
    REFERENCE_DATA_PATH,
)

# Resolve EXECUTE_FILE_PATH relative to the backend directory (mirrors app.py)
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_path(path_var, default_relative):
    """Resolve path: if relative, make it relative to backend_dir; if absolute, use as-is."""
    if os.path.isabs(path_var):
        return path_var
    return os.path.join(_backend_dir, path_var)


EXECUTE_FILE_PATH = _resolve_path(_EXECUTE_FILE_PATH, "../executables")

# Maximum upload size. Default 5GB; override with MAX_UPLOAD_MB. Enforced manually
# while streaming the upload to disk (C2) since Litestar does not bound it by default.
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_MB", str(5 * 1024))) * 1024 * 1024
# Cap cumulative DECOMPRESSED bytes from a zip to defuse zip bombs (C2).
MAX_DECOMPRESSED_SIZE = (
    int(os.getenv("MAX_DECOMPRESSED_MB", str(20 * 1024))) * 1024 * 1024
)

# Machine templates path
MACHINE_TEMPLATES_PATH = os.path.join(
    REFERENCE_DATA_PATH, "simulation", "machine_templates.json"
)

# Machines list path (contains machine specs by model name)
MACHINES_LIST_PATH = os.path.join(REFERENCE_DATA_PATH, "machines.json")

_IMPORT_FILE_TYPES = ["model", "des_inputs", "ledger", "routes_excel"]


def process_import_and_export(
    site_name: str,
    parse_result: Dict[str, Any],
    records: List[Dict[str, Any]],
    config: Dict[str, Any],
    output_base_name: str = None,
    export_model: bool = True,
    export_simulation: bool = True,
    export_routes_excel: bool = False,
):
    """Process import and export in background thread."""
    # Use output_base_name for file naming, fallback to site_name
    file_base_name = output_base_name if output_base_name else site_name

    obs.metrics.incr("import_count")
    obs.log_event("import_start", site=site_name, job="import", stage="start")
    try:
        set_import_status(
            file_base_name,
            "processing",
            10,
            "Converting imported data to telemetry format...",
        )

        # Convert imported records to telemetry tuple format
        sample_interval = config.get(
            "sample_interval", DEFAULT_CONFIG["data_fetching"]["sample_interval"]
        )
        telemetry_data = convert_imported_records_to_telemetry(
            parse_result, records, sample_interval=sample_interval
        )

        if not telemetry_data:
            set_import_status(
                file_base_name, "error", 0, "Failed to convert imported data"
            )
            return

        set_import_status(
            file_base_name,
            "processing",
            20,
            "Extracting zones using Reader.py algorithms...",
        )

        # Extract zones using standard Reader.py algorithms (Segment classification + DBSCAN)
        cycles, zones = extract_zones_from_import(parse_result)

        set_import_status(
            file_base_name, "processing", 30, "Preparing machine information..."
        )

        # Create machine info from telemetry data
        # Note: row[0] is IPAddress in the machines table, not Machine Unique Id
        machines = {}
        unique_ip_addresses = set(row[0] for row in telemetry_data)

        # Batch query to get TypeName and Machine Unique Id from database by IPAddress
        machine_types = {}
        # M5: the import path joins telemetry IPs to their `Machine Unique Id` via the
        # DB. If the DB is unavailable we cannot resolve the join key and would
        # silently fall back to the raw IP as the machine key, producing a model with
        # wrong machine identities. Treat DB-unavailable here as a loud error.
        connection = get_connection()
        if not connection:
            obs.log_event(
                "import_error",
                site=site_name,
                job="import",
                stage="db_connect",
                error="DB unavailable: cannot resolve machine identities",
            )
            set_import_status(
                file_base_name,
                "error",
                0,
                "Database unavailable: cannot resolve machine identities for import",
            )
            return
        # C1/H3: wrap DB usage in try/finally and use a context-managed cursor so the
        # connection and cursor always close, even when a query raises.
        try:
            with connection.cursor() as cursor:
                if unique_ip_addresses:
                    # Use batch query with IN clause for better performance
                    placeholders = ",".join(["%s"] * len(unique_ip_addresses))
                    ip_list = list(unique_ip_addresses)
                    cursor.execute(
                        f"SELECT `IPAddress`, `Machine Unique Id`, `TypeName`, `Name` FROM machines WHERE `IPAddress` IN ({placeholders})",
                        ip_list,
                    )
                    results = cursor.fetchall()
                    for row in results:
                        ip_address, machine_unique_id, type_name, name = row
                        machine_types[ip_address] = {
                            "machine_unique_id": machine_unique_id,
                            "type_name": type_name,
                            "name": name,
                        }
                        print(
                            f"[Import] IPAddress {ip_address}: Machine Unique Id = {machine_unique_id}, TypeName = {type_name}, Name = {name}",
                            flush=True,
                        )

                    # Log IP addresses not found in database
                    found_ips = set(machine_types.keys())
                    missing_ips = unique_ip_addresses - found_ips
                    for ip in missing_ips:
                        print(
                            f"[Import] IPAddress {ip}: Not found in database",
                            flush=True,
                        )
        finally:
            connection.close()

        for ip_address in unique_ip_addresses:
            machine_info = machine_types.get(ip_address, {})
            machines[ip_address] = {
                "machine_unique_id": machine_info.get("machine_unique_id", ip_address),
                "name": machine_info.get("name", f"Machine_{ip_address}"),
                "site_name": site_name,
                "type_name": machine_info.get("type_name", "Unknown"),
            }
            print(f"[Import] Created machine entry: {machines[ip_address]}", flush=True)

        # Load machine templates and machines list
        machine_templates = load_machine_templates(MACHINE_TEMPLATES_PATH)
        machines_list = load_machines_list(MACHINES_LIST_PATH)

        # Process site with imported telemetry data and precomputed zones
        set_import_status(
            file_base_name,
            "processing",
            40,
            "Processing site data and generating simulation files...",
        )
        obs.log_event(
            "import_process_site_start",
            site=site_name,
            job="import",
            stage="process_site",
            file_base_name=file_base_name,
        )
        result = process_site(
            cursor=None,  # No database cursor needed for imported data
            site_name=site_name,
            machines=machines,
            output_dir=OUTPUT_DIR,
            limit=config.get("limit", DEFAULT_CONFIG["data_fetching"]["limit"]),
            sample_interval=sample_interval,
            grid_size=config.get(
                "grid_size", DEFAULT_CONFIG["road_detection"]["grid_size"]
            ),
            min_density=config.get(
                "min_density", DEFAULT_CONFIG["road_detection"]["min_density"]
            ),
            simplify_epsilon=config.get(
                "simplify_epsilon", DEFAULT_CONFIG["road_detection"]["simplify_epsilon"]
            ),
            max_node_distance=config.get(
                "max_node_distance",
                DEFAULT_CONFIG["road_detection"]["max_node_distance"],
            ),
            merge_tolerance=config.get(
                "merge_tolerance", DEFAULT_CONFIG["road_detection"]["merge_tolerance"]
            ),
            zone_grid_size=config.get(
                "zone_grid_size", DEFAULT_CONFIG["zone_detection"]["grid_size"]
            ),
            zone_min_stops=config.get(
                "zone_min_stops", DEFAULT_CONFIG["zone_detection"]["min_stop_count"]
            ),
            sim_time=config.get("sim_time", DEFAULT_CONFIG["simulation"]["sim_time"]),
            machine_templates=machine_templates,
            machines_list=machines_list,
            telemetry_data=telemetry_data,
            coordinates_in_meters=True,  # Import data has coordinates in meters
            precomputed_zones=zones if zones else None,
            output_base_name=file_base_name,  # Use import filename for output naming
            export_model=export_model,
            export_simulation=export_simulation,
            export_routes_excel=export_routes_excel,
            material=config.get("material", DEFAULT_MATERIAL),
        )

        if result:
            # Convert absolute paths to relative filenames
            files = {}
            for key, path in result.items():
                if os.path.exists(path):
                    files[key] = os.path.basename(path)

            obs.metrics.observe("records_processed", len(records))
            obs.log_event(
                "import_complete",
                site=site_name,
                job="import",
                stage="done",
                files=list(files.keys()),
            )
            set_import_status(
                file_base_name,
                "completed",
                100,
                "Import and export completed successfully",
                files,
            )
        else:
            obs.log_event(
                "import_error",
                site=site_name,
                job="import",
                stage="process_site",
                error="process_site returned None",
            )
            set_import_status(file_base_name, "error", 0, "Failed to generate files")

    except Exception as e:
        import traceback

        obs.log_event(
            "import_error",
            site=site_name,
            job="import",
            stage="exception",
            error=str(e),
        )
        traceback.print_exc()
        set_import_status(file_base_name, "error", 0, f"Error: {str(e)}")


def _extract_and_parse(saved_files, temp_upload_dir, site_name, temp_base):
    """Synchronous worker: extract zips (zip-bomb guarded) and run the parser.

    Returns (file_paths, parse_result, records). Raises HttpError to surface an
    HTTP status + body to the async handler. Runs off the event loop via to_thread.
    """
    file_paths = []
    for file_path, filename in saved_files:
        # Check if it's a zip file
        if filename.lower().endswith(".zip"):
            # Extract zip file - use short directory name to avoid Windows MAX_PATH (260) limit
            extract_dir = os.path.join(temp_upload_dir, f"e{len(file_paths)}")
            os.makedirs(extract_dir, exist_ok=True)

            try:
                with zipfile.ZipFile(file_path, "r") as zip_ref:
                    # Count valid files for progress bar
                    valid_files = [
                        zi
                        for zi in zip_ref.infolist()
                        if not zi.is_dir() and not zi.filename.lower().endswith(".zip")
                    ]
                    total_files = len(valid_files)
                    print(f"\n[ZIP] Extracting {total_files} files from {filename}")

                    # Extract files one by one with short names to avoid MAX_PATH limit
                    file_idx = 0
                    total_decompressed = 0  # zip-bomb guard (C2)
                    for zip_info in tqdm(valid_files, desc="Extracting", unit="file"):
                        # Get original extension
                        orig_name = os.path.basename(zip_info.filename)
                        _, ext = os.path.splitext(orig_name)

                        # Create short filename: f0.dat, f1.dat, etc.
                        short_name = f"f{file_idx}{ext}"
                        target_path = os.path.join(extract_dir, short_name)

                        # Extract in chunks, counting ACTUAL decompressed bytes so a
                        # zip bomb (lying about file_size) can't exhaust disk (C2).
                        with (
                            zip_ref.open(zip_info) as src,
                            open(target_path, "wb") as dst,
                        ):
                            while True:
                                chunk = src.read(8 * 1024 * 1024)
                                if not chunk:
                                    break
                                total_decompressed += len(chunk)
                                if total_decompressed > MAX_DECOMPRESSED_SIZE:
                                    raise HttpError(
                                        400,
                                        {
                                            "error": (
                                                "Decompressed archive exceeds the "
                                                f"{MAX_DECOMPRESSED_SIZE // (1024 * 1024)} MB limit"
                                            )
                                        },
                                    )
                                dst.write(chunk)

                        file_paths.append(target_path)
                        file_idx += 1
            except zipfile.BadZipFile:
                raise HttpError(400, {"error": f"Invalid zip file: {filename}"})
        else:
            file_paths.append(file_path)

    if not file_paths:
        raise HttpError(400, {"error": "No valid files found"})

    # Parse files using gateway parser
    # Pass temp_base to avoid Windows MAX_PATH (260) limit
    parse_result = parse_gateway_files(
        site_name=site_name,
        file_paths=file_paths,
        parser_exe_path=EXECUTE_FILE_PATH,
        temp_base_dir=temp_base,
    )

    # Check if parsing was successful
    if "error" in parse_result:
        raise HttpError(
            400,
            {
                "success": False,
                "error": parse_result.get("error"),
                "details": parse_result.get("details", []),
            },
        )

    # Process parser output using same logic as parse_gateway_messages.py
    # Returns list of dicts with database column names
    records = process_parser_output(parse_result)
    return file_paths, parse_result, records


class ImportController(Controller):
    path = "/api/imports"

    @post()
    async def create(self, request: Request) -> Response:
        """
        Import and parse raw data files.

        Accepts:
        - Single ZIP file containing raw data files (multipart field "files")

        Form fields:
        - export: If "true", will also export simulation files after import

        Returns parsed JSON data, or starts export process if export=true.
        """
        try:
            form = await request.form()

            # Check if files are in request
            files = form.getall("files", [])
            files = [f for f in files if getattr(f, "filename", None) is not None]
            if not files:
                return json_error({"error": "No files provided"}, 400)
            if not files[0].filename:
                return json_error({"error": "No files selected"}, 400)

            # Validate: only accept single .zip file
            if len(files) != 1:
                return json_error({"error": "Please upload exactly one ZIP file"}, 400)
            if not files[0].filename.lower().endswith(".zip"):
                return json_error({"error": "Only ZIP files are allowed"}, 400)

            # Get site_name from form data (optional, default to "DefaultSite")
            site_name = form.get("site_name", "DefaultSite")

            # Get output_base_name from form data (used for output file naming)
            # This allows naming output files based on input filename (e.g., ABC.zip -> ABC_model.json)
            # M1: this is a user-supplied value that flows into output filenames, so run it
            # through secure_filename at the API boundary to strip traversal sequences and
            # path separators. secure_filename("") -> "", so normalize an empty result back
            # to None to preserve the site_name fallback.
            output_base_name = form.get("output_base_name", None)
            if output_base_name:
                output_base_name = secure_filename(output_base_name) or None

            # Check if export is requested
            export_after_import = str(form.get("export", "false")).lower() == "true"

            # Get export configuration from form data (optional)
            config = {}
            export_model = True
            export_simulation = True
            export_routes_excel = False
            if export_after_import:
                config = {
                    "limit": int(
                        form.get("limit", DEFAULT_CONFIG["data_fetching"]["limit"])
                    ),
                    "sample_interval": int(
                        form.get(
                            "sample_interval",
                            DEFAULT_CONFIG["data_fetching"]["sample_interval"],
                        )
                    ),
                    "grid_size": float(
                        form.get(
                            "grid_size", DEFAULT_CONFIG["road_detection"]["grid_size"]
                        )
                    ),
                    "min_density": int(
                        form.get(
                            "min_density",
                            DEFAULT_CONFIG["road_detection"]["min_density"],
                        )
                    ),
                    "simplify_epsilon": float(
                        form.get(
                            "simplify_epsilon",
                            DEFAULT_CONFIG["road_detection"]["simplify_epsilon"],
                        )
                    ),
                    "zone_grid_size": float(
                        form.get(
                            "zone_grid_size",
                            DEFAULT_CONFIG["zone_detection"]["grid_size"],
                        )
                    ),
                    "zone_min_stops": int(
                        form.get(
                            "zone_min_stops",
                            DEFAULT_CONFIG["zone_detection"]["min_stop_count"],
                        )
                    ),
                    "sim_time": int(
                        form.get("sim_time", DEFAULT_CONFIG["simulation"]["sim_time"])
                    ),
                }
                # Get export file type options
                export_model = str(form.get("export_model", "true")).lower() == "true"
                export_simulation = (
                    str(form.get("export_simulation", "true")).lower() == "true"
                )
                export_routes_excel = (
                    str(form.get("export_routes_excel", "false")).lower() == "true"
                )

                # At least one type must be selected
                if (
                    not export_model
                    and not export_simulation
                    and not export_routes_excel
                ):
                    return json_error(
                        {"error": "At least one export type must be selected"}, 400
                    )

                # Validate material name before any file work (Task 4).
                import_material, material_err = resolve_material(form.get("material"))
                if material_err:
                    return material_err
                config["material"] = import_material

            # Validate parser executable
            if not EXECUTE_FILE_PATH or not os.path.exists(EXECUTE_FILE_PATH):
                return json_error(
                    {
                        "error": "Parser executable not found. Please configure EXECUTE_FILE_PATH in .env"
                    },
                    500,
                )

            # Create temporary directory for uploaded files
            # Use TEMP_DIR from env or system temp to avoid Windows MAX_PATH (260) limit
            temp_base = TEMP_DIR if TEMP_DIR else None
            if temp_base and not os.path.exists(temp_base):
                os.makedirs(temp_base, exist_ok=True)
            temp_upload_dir = tempfile.mkdtemp(prefix="imp_", dir=temp_base)
            saved_files = []

            try:
                # Stream uploaded files to disk, enforcing the upload size cap (C2).
                chunk_size = 64 * 1024 * 1024  # 64MB
                total_uploaded = 0
                for file in files:
                    if not file.filename:
                        continue

                    filename = secure_filename(file.filename)
                    file_path = os.path.join(temp_upload_dir, filename)

                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await file.read(chunk_size)
                            if not chunk:
                                break
                            total_uploaded += len(chunk)
                            if total_uploaded > MAX_UPLOAD_SIZE:
                                return json_error(
                                    {
                                        "error": (
                                            f"Upload exceeds the {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit"
                                        )
                                    },
                                    413,
                                )
                            f.write(chunk)

                    saved_files.append((file_path, filename))

                # Extract + parse (synchronous; the external parser dominates the wall
                # time here). Single-worker PoC, so we accept blocking this request.
                try:
                    file_paths, parse_result, records = _extract_and_parse(
                        saved_files, temp_upload_dir, site_name, temp_base
                    )
                except HttpError as he:
                    return json_error(he.body, he.status)

                if export_after_import:
                    # Use output_base_name for SSE key and file naming
                    sse_key = output_base_name if output_base_name else site_name

                    # Start export in background thread
                    thread = threading.Thread(
                        target=process_import_and_export,
                        args=(
                            site_name,
                            parse_result,
                            records,
                            config,
                            output_base_name,  # Pass output_base_name for file naming
                            export_model,
                            export_simulation,
                            export_routes_excel,
                        ),
                    )
                    thread.daemon = True
                    thread.start()

                    return Response(
                        content={
                            "success": True,
                            "message": "Import completed, export started",
                            "site_name": site_name,
                            "output_base_name": sse_key,  # Return the key for SSE subscription
                            "files_processed": len(file_paths),
                            "records_count": len(records),
                            "export_status": "processing",
                        },
                        media_type=MediaType.JSON,
                        status_code=202,
                        headers={"Location": f"/api/imports/{sse_key}"},
                    )

                # Prepare response matching parse_gateway_messages.py output format
                response_data = {
                    "success": True,
                    "site_name": site_name,
                    "files_processed": len(file_paths),
                    "records_count": len(records),
                    "records": records,
                }

                return json_error(response_data, 200)

            finally:
                # Cleanup temporary directory
                try:
                    shutil.rmtree(temp_upload_dir, ignore_errors=True)
                except Exception:
                    pass

        except Exception as e:
            return json_error({"error": str(e)}, 500)

    @get("/{site_name:str}")
    async def state(self, site_name: Annotated[str, Parameter()]) -> Response:
        """Get import+export status for a site."""
        return json_error(get_import_status(site_name), 200)

    @get("/{site_name:str}/events")
    async def events(self, site_name: Annotated[str, Parameter()]) -> ServerSentEvent:
        """SSE endpoint for real-time import status updates."""
        return sse_response("import", site_name)

    @get("/{site_name:str}/files/{file_type:str}")
    async def files(
        self,
        site_name: Annotated[str, Parameter()],
        file_type: Annotated[str, Parameter()],
    ) -> Response:
        """Download exported file from import."""
        return serve_job_file(
            get_import_status(site_name),
            file_type,
            _IMPORT_FILE_TYPES,
            not_completed_msg="Import/export not completed",
        )
