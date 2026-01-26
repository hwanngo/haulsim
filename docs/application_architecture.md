# Application Architecture

> Architecture and business-logic reference. For setup, running, and the API
> quickstart, see the [project README](../README.md). For the generated-file
> formats, see the other docs in [this folder](README.md).

## Overview

The AMT Cycle Workbench is a web application designed to process, analyze, and export mining telemetry data from Autonomous Mining Trucks (AMT). The application transforms raw gateway message files into structured simulation data, enabling productivity analysis, cycle optimization, and discrete event simulation (DES) modeling.

### Primary Functions

1. **Data Import**: Parse raw gateway message files (`.gwm`, `.dat`, `.bin`) into structured telemetry data
2. **Data Export**: Generate simulation-ready files (model, DES inputs, events ledger) from database or imported data
3. **Cycle Analysis**: Extract and analyze machine cycles (dump-to-dump operations) with productivity metrics
4. **Zone Detection**: Automatically identify load and dump zones from machine movement patterns
5. **Road Network Generation**: Create road network models from telemetry path data
6. **Loss Analysis**: Calculate productivity losses and efficiency metrics based on ASLR (Autonomous Speed Limit Reason) codes

## Table of Contents

1. [Technical Architecture](#1-technical-architecture)
2. [Project Structure](#2-project-structure)
3. [Core Business Logic](#3-core-business-logic)
4. [Data Flow](#4-data-flow)
5. [API Endpoints](#5-api-endpoints)
6. [Business Rules and Validations](#6-business-rules-and-validations)
7. [Key Components](#7-key-components)
8. [Configuration](#8-configuration)
9. [Performance Considerations](#9-performance-considerations)
10. [Security Considerations](#10-security-considerations)
11. [Future Enhancements](#11-future-enhancements)

## 1. Technical Architecture

### 1.1 System Architecture

The application follows a **client-server architecture** with clear separation of concerns:

```
┌─────────────────┐
│   React Frontend │  (Port 3000)
│   - UI Components│
│   - State Mgmt   │
└────────┬─────────┘
         │ HTTP/REST API
         │
┌────────▼─────────┐
│ Litestar Backend │  (Port 5001, granian)
│  - REST API      │
│  - Business Logic│
│  - Data Processing│
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌──▼────┐
│DuckDB │ │ File │
│ file  │ │System│
└───────┘ └──────┘
```

### 1.2 Technology Stack

**Backend:**
- **Framework**: Litestar (ASGI, Python 3.14, managed with uv), served by granian (Rust ASGI server)
- **Database**: DuckDB (embedded, file-based; no server)
- **Data Processing**: Polars, NumPy, Shapely, scikit-learn; msgspec for JSON output
- **External Parser**: GWMReader.exe (cross-platform Python clone of the proprietary gateway-message parser)

**Frontend:**
- **Framework**: React 19 + TypeScript, built with Vite (managed with pnpm, Node 22)
- **UI Library**: Chakra UI v3 ("CAT" design system)
- **State Management**: React Hooks (useState, useEffect)
- **HTTP Client**: Fetch API (with Server-Sent Events for live import/export progress)
- **Validation**: Zod (request/response schema parsing)
- **PWA / Testing**: vite-plugin-pwa; Vitest + React Testing Library for unit tests

**Data Processing Libraries:**
- **Spatial Analysis**: Shapely (geometric operations), DBSCAN (clustering)
- **Data Manipulation**: Polars (DataFrames), NumPy (numerical operations)
- **Time Handling**: Python datetime, GPS epoch calculations

## 2. Project Structure

```
<repo root>/                    # backend/ and frontend/ live at the repository root
                                # (there is no webapp/ wrapper directory)
├── backend/                    # Litestar REST API and processing logic
│   ├── app.py                  # Thin controller wiring (~62 lines): mounts ExportController,
│   │                           #   ImportController, SystemController onto the Litestar app
│   ├── api/                    # Resource-oriented HTTP controllers (added in REST refactor)
│   │   ├── jobs.py             # Shared job machinery: status stores, SSE, validation,
│   │   │                       #   file/error helpers (json_error, serve_job_file, sse_response,
│   │   │                       #   resolve_material, validate_export_config, etc.)
│   │   ├── exports.py          # ExportController — POST /api/exports + /{site}/events/files
│   │   ├── imports.py          # ImportController — POST /api/imports + /{name}/events/files
│   │   └── system.py           # SystemController — /api/sites, /materials, /health, /metrics
│   ├── job_store.py            # DuckDB-backed durable export/import job state
│   ├── obs.py                  # Structured JSON logging + thread-safe metrics
│   ├── core/                   # Core AMT processing modules (import/cycle-analysis path)
│   │   ├── reader.py           # Main data parser (CP1/CP2 format), DBSCAN zone clustering
│   │   ├── cycle.py            # Cycle object and business logic
│   │   ├── segment.py          # Segment classification and analysis
│   │   ├── zone.py             # Zone object + DBSCAN clustering / convex hulls
│   │   ├── loss_bucket.py      # ASLR loss-bucket aggregation
│   │   ├── map_classes.py      # Node/road/route model classes
│   │   ├── amt_cycle_prod_info_message.py  # Message data structure
│   │   ├── gateway_parser_wrapper.py   # GWMReader.exe wrapper
│   │   ├── gateway_data_converter.py  # Data format conversion (process_parser_output, convert_imported_records_to_telemetry)
│   │   ├── reader_config.py    # Reader tuning constants
│   │   ├── db_config.py        # Database configuration (paths)
│   │   └── constants.py        # Enums and constants
│   ├── scripts/                # Standalone processing scripts
│   │   ├── simulation_generator.py    # Export facade: re-exports simgen/*, hosts
│   │   │                              #   process_site() + create_roads_from_trajectories()
│   │   ├── simgen/             # Decomposed export package (re-exported by the facade)
│   │   │   ├── constants.py    #   defaults, thresholds, DEFAULT_MATERIAL
│   │   │   ├── geometry.py     #   Douglas-Peucker, distance/polyline utilities
│   │   │   ├── loaders.py      #   config/machine/material loading, material catalog,
│   │   │   │                   #     resolve_zone_material_assignment
│   │   │   ├── db.py           #   DuckDB fetch (ordered queries for determinism)
│   │   │   ├── zones.py        #   stop/grid + payload-transition zone detection
│   │   │   ├── roads.py        #   overlap merge, intersection split, "_Shared" dedup
│   │   │   ├── routes.py       #   route/lap creation (BFS pathfinding)
│   │   │   ├── specs.py        #   default hauler/loader machine specs
│   │   │   ├── operations.py   #   trip analysis, material schedule, Excel export
│   │   │   ├── model.py        #   model.json assembly (haulers, loaders, stations)
│   │   │   └── des.py          #   des_inputs.json assembly (per-zone material refs)
│   │   └── config.json         # Configuration file
│   ├── simulation_analysis/     # Event conversion modules
│   │   ├── gps_to_events_converter.py
│   │   ├── event_generator.py
│   │   ├── road_navigator.py
│   │   └── node_matcher.py
│   └── tests/                  # pytest suite (+ golden/ baselines for determinism)
├── frontend/                   # React + TypeScript + Vite + Chakra UI (pnpm)
│   ├── src/
│   │   ├── main.tsx            # React entry point
│   │   ├── App.tsx             # Main application component
│   │   ├── components/
│   │   │   ├── ImportButton.tsx # Import + export trigger UI
│   │   │   ├── ExportPanel.tsx  # Database-export screen (site/material/config + SSE)
│   │   │   ├── ExportToggle.tsx # Shared export-toggle control
│   │   │   └── AboutModal.tsx   # About dialog
│   │   ├── system.ts          # Chakra theme (CAT design)
│   │   └── types.ts           # Shared TypeScript types
│   ├── vite.config.ts          # dev server + /api proxy
│   ├── tsconfig.json
│   └── package.json
├── reference_data/             # machines.json, materials.json, haul_road_design.json
├── db/                         # embedded DuckDB (catalog + seed builder)
├── executables/GWMReader.exe   # cross-platform parser clone
├── tools/generate_gwm.py       # builds uploadable .gwm import samples
└── docs/                       # Documentation (this file + generated-file specs)
```

## 3. Core Business Logic

### 3.1 Data Processing Pipeline

#### Import Flow

```
Raw Gateway Files (.gwm/.dat/.bin)
    ↓
GWMReader.exe Parser
    ↓
JSON Output (CycleProdInfo structure)
    ↓
process_parser_output() → List[Dict] (DB column format)
    ↓
convert_imported_records_to_telemetry() → List[Tuple] (telemetry format)
    ↓
AMTCycleProdInfoReader.parse_cp1_data() → (Cycles, Zones)
```

#### Export Flow

```
Database Telemetry OR Imported Telemetry
    ↓
process_site()
    ↓
├── Road Detection (grid-based clustering)
├── Zone Detection (stop-based clustering)
├── Cycle Analysis (segment classification)
└── Event Generation (GPS to events conversion)
    ↓
Output Files:
├── model.json (road network, nodes, zones)
├── des_inputs.json.gz (simulation configuration; gzipped)
└── ledger.json.gz (events timeline; gzipped)
```

### 3.2 Cycle Detection Logic

**Business Rules:**

1. **Cycle Definition**: A cycle represents a complete dump-to-dump operation
   - Starts when machine leaves dump zone (empty state)
   - Ends when machine returns to dump zone (after loading)

2. **Cycle Identification (CP1 Format)**:
   - Cycles are grouped by `segmentId` (GPS timestamp)
   - Contiguous messages with same `segmentId` form a segment
   - Segments are classified based on payload percentage and next segment payload
   - Cycle ends when segment type transitions from loaded to empty (payload ≤ 50%)

3. **Cycle Identification (CP2 Format)**:
   - Cycles are explicitly identified by `cycleId` field
   - Messages grouped by `cycleId` form complete cycles
   - Simpler classification: empty segment (payload ≤ 50%) followed by loaded segment

4. **Full Cycle Validation**:
   - A cycle is considered "full" only if both `dumpZoneStart` and `dumpZoneEnd` are identified
   - Incomplete cycles (missing zones) are marked as `isFullCycle = False`

### 3.3 Segment Classification

**Segment Types:**
- `SPOTTING_AT_SOURCE`: Machine reversing with payload transition from empty (≤50%) to loaded (>50%)
- `SPOTTING_AT_SINK`: Machine reversing with payload transition from loaded (>50%) to empty (≤50%)
- `TRAVELLING_EMPTY`: Machine moving with payload ≤ 50%
- `TRAVELLING_FULL`: Machine moving with payload > 50%

**Classification Rules:**

1. **Payload Threshold**: 50% is the critical threshold separating empty and loaded states
2. **Reversing Detection**: Machine is considered reversing if `actualSpeed > 0` and `expectedSpeed > 0` (initially `isReversing = True`)
3. **Next Payload Analysis**: Segment type depends on:
   - Current segment payload
   - Next segment payload (if available)
   - Reversing state
4. **Cycle End Detection**: Cycle ends when:
   - Segment type is `SPOTTING_AT_SINK` (for CP1)
   - Payload transitions from loaded to empty (for CP2)

### 3.4 Zone Detection

**Load Zone Detection:**
- Extracts GPS points from segments with type `SPOTTING_AT_SOURCE`
- Uses DBSCAN clustering (epsilon = 50 meters) to group points
- Creates convex hull polygons around clustered points
- Minimum 2 points required to form a zone polygon

**Dump Zone Detection:**
- Extracts GPS points from segments with type `SPOTTING_AT_SINK`
- Same clustering and polygon generation logic as load zones

**Business Rules:**
- Zone points are collected from "spotting" segments (reversing at load/dump locations)
- Noise points (DBSCAN label = -1) are filtered out
- Zones with fewer than 2 unique points use a 5-meter buffer around the point
- Zone polygons represent operational areas where machines load or dump material

### 3.5 Road Network Generation

**Road Detection Algorithm:**

1. **Grid-Based Clustering**:
   - Telemetry points are binned into a grid (default: 5m × 5m cells)
   - Cells with density ≥ `min_density` (default: 3 points) are considered road cells
   - Road cells are converted to nodes

2. **Road Simplification**:
   - Douglas-Peucker algorithm (epsilon = 5.0m) simplifies road paths
   - Reduces computational complexity while preserving road shape

3. **Node and Road Creation**:
   - Nodes represent road intersections and key points
   - Roads connect nodes based on machine travel patterns
   - Road properties include: distance, average efficiency, loss summary

4. **Road Intersection Splitting**:
   - Roads can only share nodes at start or end points
   - If roads share nodes in the middle, they are split at intersection points
   - Overlapping segments are deduplicated and marked with "_Shared" suffix
   - Routes are updated to reference new segment IDs

### 3.6 Loss Analysis

**Productivity Loss Calculation:**

1. **Loss Bucket Creation**:
   - Segments are divided into "loss buckets" based on ASLR (Autonomous Speed Limit Reason) changes
   - Each bucket represents a continuous period with the same ASLR code
   - Bucket loss = `actualTimeTaken - expectedTimeTaken` (in seconds)

2. **Efficiency Calculation**:
   - Segment efficiency = `(expectedTimeTaken / actualTimeTaken) * 100`
   - Cycle efficiency = weighted average of segment efficiencies
   - Route efficiency = average of all lap efficiencies

3. **Loss Summary Aggregation**:
   - Loss summaries are aggregated by ASLR reason code
   - Summaries track: total loss, count, actual/expected time, efficiency
   - Aggregation occurs at segment → cycle → route levels

**ASLR Reason Categories:**
- **Operations-Office**: Assignment limits, bed down areas
- **Machine Limited**: Base machine speed limits, power limitations
- **Non-Diagnostic Limited**: A-Stop, path avoidance areas
- **Diagnostic**: Health events, system diagnostics

### 3.7 Event Generation

**GPS to Events Conversion:**

The application converts GPS telemetry data into discrete events for simulation:

1. **State Detection**: Identifies machine states (TRAVEL_LOADED, TRAVEL_UNLOADED, LOADING, DUMPING, etc.)
2. **Event Creation**: Generates state transition events with timestamps
3. **Location Mapping**: Maps GPS coordinates to road network nodes and zones
4. **Event Ledger**: Creates chronological sequence of events for simulation playback

## 4. Data Flow

### 4.1 Import Data Flow

```
User uploads files → Litestar receives multipart/form-data
    ↓
Files saved to temp directory
    ↓
ZIP extraction (if applicable)
    ↓
GWMReader.exe execution (all files in single command)
    ↓
JSON output parsed from stderr
    ↓
process_parser_output() converts to DB format
    ↓
Response: {success, records_count, records[]}
```

### 4.2 Export Data Flow

```
User selects site → POST /api/exports
    ↓
Background thread: process_export()
    ↓
Fetch machines from database
    ↓
Fetch telemetry data (with limit, sample_interval)
    ↓
process_site():
    ├── Detect roads (grid clustering)
    ├── Split roads at intersections
    ├── Detect zones (stop clustering)
    ├── Analyze cycles
    └── Generate events
    ↓
Create output files:
    ├── model.json
    ├── des_inputs.json
    └── ledger.json
    ↓
Status: completed → Files available for download
```

### 4.3 Import + Export Flow

```
User uploads files with export=true
    ↓
Import processing (same as above)
    ↓
convert_imported_records_to_telemetry()
    ↓
Create machine info from telemetry
    ↓
process_site() with telemetry_data parameter:
    ├── Detect roads (grid clustering)
    ├── Split roads at intersections
    ├── Detect zones (stop clustering)
    ├── Analyze cycles
    └── Generate events
    ↓
Generate simulation files
    ↓
Status: completed → Files available for download
```

## 5. API Endpoints

### 5.1 Site Management

**GET `/api/sites`**
- Returns list of available sites from database
- Response: `{sites: [{site_name, site_short, site_id}]}`

### 5.2 Export Endpoints

**POST `/api/exports`**
- Starts export process for a site (background thread `process_export()`)
- Request: `{site_name, config: {material, zone_materials, limit, sample_interval,
  simplify_epsilon, max_node_distance, merge_tolerance, zone_grid_size,
  zone_min_stops, sim_time, ...}}` plus optional `export_model`, `export_simulation`,
  `export_routes_excel` flags. (`grid_size` / `min_density` are accepted by the
  schema but unused by the current detection path — see the deferred backlog.)
- Validation is fail-fast: out-of-range numeric params, booleans passed where a
  number is expected, and unknown materials return **400** before the job starts.
- Concurrent export of the same site returns **409 Conflict**.
- Response: `{message, site_name}`; `Location: /api/exports/{site_name}`
- Status: 202 Accepted (async processing)

**GET `/api/exports/{site_name}`**
- Job-state resource: returns export status and progress (subsumes the old `/status` path)
- Response: `{status, progress, message, files, load_zones?}`
- Status values: `idle`, `processing`, `completed`, `interrupted`, `error`

**GET `/api/exports/{site_name}/events`** (Server-Sent Events)
- Streams live progress for an export. The export-complete event carries
  `load_zones: [{id, name, hint}]` where `hint` is the zone's detected `{x, y, z}`
  centroid (or `null`). This is read from `model.json` only at response time and is
  **never** serialized back into any artifact (model/des_inputs/ledger stay
  byte-identical). Operators use it to assign per-zone materials on re-export.

**GET `/api/exports/{site_name}/files/{file_type}`**
- Downloads a generated file
- File types: `model`, `des_inputs`, `ledger`, `routes_excel` (`des_inputs` / `ledger` are gzipped)

### 5.3 Import Endpoints

**POST `/api/imports`**
- Imports and parses raw gateway message files
- Request: `multipart/form-data` with `files` and optional `site_name`, `export`,
  `output_base_name`
- Supports: single ZIP archive
- Response: `{success, site_name, files_processed, records_count, records[]}`
- If `export=true`: Returns 202, starts background export, `Location: /api/imports/{name}`
  where `{name}` is `output_base_name` if supplied, otherwise `site_name`

**GET `/api/imports/{name}`**
- Job-state resource: returns import+export status (same format as export job resource)

**GET `/api/imports/{name}/events`** (Server-Sent Events)
- Streams live import+export progress (same event shape as the export SSE stream)

**GET `/api/imports/{name}/files/{file_type}`**
- Downloads exported file from import process
- File types: `model`, `des_inputs`, `ledger`, `routes_excel` (same as export download)

### 5.4 REST Conventions

The API follows resource-oriented REST conventions:

- **Plural collections**: `/api/exports` and `/api/imports` are the collection resources.
- **Job resources**: Each submitted job is a resource at `/{site_name}` (export) or
  `/{name}` (import), with `events` and `files` sub-resources for SSE streaming and
  file download respectively.
- **`Location` header on `202`**: Both POST endpoints return `202 Accepted` with a
  `Location` header pointing to the job-state resource (`GET /{site_name}` or `GET /{name}`).
- **Site/name-keyed**: Jobs are keyed by site name (export) or `output_base_name` /
  `site_name` (import). A concurrent export for the same site returns `409 Conflict`.

### 5.5 Health Check

**GET `/api/health`**
- Health check endpoint
- Response: `{status: "ok"}`

### 5.6 Reference & Observability

**GET `/api/materials`**
- Lists the materials from `reference_data/materials.json` (single source of truth
  via the same loader the export uses) for the export UI's material selector
- Response: `{materials: [{name, display_name}]}`

**GET `/api/metrics`**
- Read-only in-process counters/timers (import count, export count, export failures,
  export duration, records processed). Structured JSON logs go to stderr (never into
  the generated artifacts)
- Response: `{import_count, export_count, export_failures, export_duration_last, records_processed, ...}`

## 6. Business Rules and Validations

### 6.1 Import Validations

1. **File Validation**:
   - Files must be provided in request (`files` field required)
   - Supported formats: `.gwm`, `.dat`, `.bin`, or no extension
   - ZIP files are automatically extracted
   - Maximum upload size: 5 GB per request

2. **Parser Validation**:
   - Parser executable (`GWMReader.exe`) must exist at configured path
   - Parser must return exit code 0 for successful parsing
   - JSON output must be valid and parseable

3. **Data Validation**:
   - Each message array must have exactly 24 elements
   - Missing or invalid fields are handled with safe conversion functions
   - Payload values > 200 are decoded using formula: `value - 255`

### 6.2 Export Validations

1. **Site Validation**:
   - Site name must be provided
   - Site must exist in database
   - At least one machine must be associated with the site

2. **Configuration Validation** (`_validate_export_config`, fail-fast HTTP 400):
   - `limit`: Maximum number of telemetry records to process — int > 0 (default: 100,000)
   - `sample_interval`: Time interval between samples in seconds — int > 0 (default: 5)
   - `simplify_epsilon`: Road simplification tolerance in meters — number > 0 (default: 5.0)
   - `max_node_distance`: Max gap before a trajectory is split — number > 0
   - `merge_tolerance`: Node-merge tolerance in meters — number >= 0
   - `zone_grid_size`: Zone detection grid size in meters — number > 0 (default: 10.0)
   - `zone_min_stops`: Minimum stops required for zone detection — int >= 1 (default: 20)
   - `sim_time`: Simulation time in minutes — number > 0 (default: 480)
   - Booleans are rejected where a number is expected (`isinstance(True, int)` is `True`
     in Python, so this is checked explicitly).
   - `material`: unknown material name → 400; omitted → site default (`copper_ore`).
   - `zone_materials` ({load_zone_id: material_name}): non-object → 400; non-int key → 400;
     unknown material value → 400; a stale/unmatched zone-id key → accepted (202) with a
     warning and that zone falls back to the site default.
   - (`grid_size` / `min_density` are legacy road-detection knobs that are accepted by the
     request schema but are neither exposed in the UI nor covered by this guard — see the
     deferred backlog.)

3. **Concurrent Export Prevention**:
   - Only one export per site can run simultaneously
   - Attempting to start export while another is processing returns 409 Conflict

### 6.3 Cycle Processing Rules

1. **Cycle Completeness**:
   - Cycles must have at least one segment
   - Full cycles require both dump zone start and end identification
   - Incomplete cycles are still processed but marked as `isFullCycle = False`

2. **Segment Classification Rules**:
   - Payload threshold of 50% determines empty vs. loaded classification
   - Segment type depends on payload transitions and reversing state
   - Cycle end is detected when payload drops from loaded to empty

3. **Zone Extraction Rules**:
   - Zone points are only extracted from "spotting" segments
   - Load zones: `SPOTTING_AT_SOURCE` segments
   - Dump zones: `SPOTTING_AT_SINK` segments
   - Minimum 2 points required to form a valid zone polygon

4. **Road Intersection Rules**:
   - Roads can only share nodes at their start or end points
   - If roads share nodes in the middle, they are split at those intersection points
   - Overlapping road segments (same start/end nodes) are deduplicated
   - Shared segments are named with "_Shared" suffix (e.g., "Road_1_Shared")
   - Routes are automatically updated to reference new segment IDs

### 6.4 Data Processing Rules

1. **Coordinate System**:
   - Database telemetry coordinates are stored in **millimetres**; the backend divides by 1000 to get metres
   - The import / `.gwm` path supplies coordinates already in **metres** (`coordinates_in_meters=True`)
   - GPS coordinates use Easting (X), Northing (Y), Elevation (Z)
   - Time values are in seconds

2. **Time Handling**:
   - GPS timestamps are converted using GPS epoch (Jan 6, 1980) + leap seconds offset
   - ISO timestamp strings are parsed with timezone support
   - All times are normalized to UTC

3. **Payload Encoding**:
   - Payload percentage range: 0-200 (normal) or >200 (special encoding)
   - Values > 200: decoded as `value - 255`
   - Database uses 255 to represent unknown payload

4. **Loss Calculation Rules**:
   - Loss = actual time - expected time (positive = delay, negative = ahead of schedule)
   - Efficiency = (expected time / actual time) × 100
   - Loss buckets are created when ASLR reason changes
   - Loss summaries aggregate at segment, cycle, and route levels

### 6.5 Machine Filtering Rules

1. **Event-Based Machine Inclusion**:
   - During simulation generation (both database export and import+export flows), only machines that generate at least one event in the GPS-to-events conversion stage are included in the DES inputs.
   - Machines (typically haulers) that do not produce any events are excluded from the `des_inputs.json` configuration, so they do not appear as active resources in the simulation model.

2. **Business Intent**:
   - Avoids cluttering the simulation with machines that have no operational activity in the selected dataset or time window.
   - Ensures that simulation results and productivity metrics focus only on machines that contributed actual events.

## 7. Key Components

### 7.1 Backend Components

**AMTCycleProdInfoReader** (`core/reader.py`):
- Main parser for CP1 and CP2 data formats
- Converts raw message tuples into Cycle and Zone objects
- Handles segment grouping and classification
- Extracts zone points from spotting segments

**Cycle** (`core/cycle.py`):
- Represents a complete dump-to-dump operation
- Tracks segments, messages, loss summary, efficiency
- Validates cycle completeness (full cycle detection)
- Aggregates segment-level metrics

**Segment** (`core/segment.py`):
- Represents a portion of a cycle with consistent payload state
- Classifies segment type based on payload and transitions
- Creates loss buckets based on ASLR changes
- Tracks path, distance, and time metrics

**Zone** (`core/zone.py`):
- Represents load or dump operational areas
- Uses DBSCAN clustering to group GPS points
- Creates convex hull polygons for zone boundaries
- Tracks associated cycle IDs

**GatewayParserWrapper** (`core/gateway_parser_wrapper.py`):
- Wraps GWMReader.exe executable
- Handles file validation and parser execution
- Manages retry logic and error handling
- Parses JSON output from parser stderr

**simulation_generator** (`scripts/simulation_generator.py`):
- Thin facade for the export pipeline: re-exports the `scripts/simgen/` package
  (`from backend.scripts.simgen.X import *`) and hosts the top-level orchestration —
  `process_site(...)` and `create_roads_from_trajectories(...)` (grid clustering +
  Douglas-Peucker road build).
- The decomposed logic now lives in `simgen/`: `roads.py` (intersection splitting,
  `_Shared` dedup), `zones.py` (stop/grid + payload-transition detection), `routes.py`
  (route/lap creation), `loaders.py` (config/machine/material loading + material
  catalog), `db.py` (ordered DuckDB fetch), `geometry.py` (Douglas-Peucker / distance),
  `operations.py`, `specs.py`, `model.py` (model.json), `des.py` (des_inputs.json).
- Output is byte-deterministic (ordered DB queries + sorted set iteration), guarded by
  golden + multi-material golden + ≥3-run determinism tests under `backend/tests/`.

**job_store** (`job_store.py`):
- DuckDB-backed durable export/import job state (`init_job_store`, `persist`,
  `load_all`); on startup reconciles orphaned `processing` jobs to `interrupted`.

**obs** (`obs.py`):
- Structured JSON logging to stderr + thread-safe in-process metrics
  (`import_count`, `export_count`, `export_failures`, `export_duration_last`,
  `records_processed`), surfaced read-only at `GET /api/metrics`.

### 7.2 Frontend Components

**App.tsx**:
- Main application component
- Renders the page shell, an Import / Export mode toggle, and the `AboutModal`
- Switches between `ImportButton` (Import Raw Data) and `ExportPanel` (Export from Database)

**components/ImportButton.tsx**:
- Handles file upload (drag-and-drop or file picker)
- Accepts a single ZIP archive of raw gateway captures
- Displays upload progress and parsing status (live via Server-Sent Events)
- Triggers export after import and polls status
- Provides download links for the generated files

**components/ExportPanel.tsx**:
- Database-export screen: site picker, material selector (from `GET /api/materials`),
  per-load-zone material assignment, export config, live SSE progress, and downloads
- Surfaces the last export's detected load zones (from the export-complete SSE event)
  for per-zone material assignment on re-export

**components/ExportToggle.tsx**:
- Shared export-enable toggle de-duplicated from the Import and Export panels

**components/AboutModal.tsx**:
- About dialog describing the workbench

**system.ts** / **types.ts**:
- `system.ts`: Chakra UI v3 theme (the "CAT" design system)
- `types.ts`: shared TypeScript types for API requests/responses

## 8. Configuration

### 8.1 Environment Variables

All configuration is managed through `.env` file in `backend/` directory:

**Database Configuration:**
- `DUCKDB_PATH`: Path to the embedded DuckDB database file (default: `../db/haulsim.duckdb`;
  `/app/db/haulsim.duckdb` in the container). Built by `db/generate_seed.py`; opened read-only.

**Path Configuration:**
- `OUTPUT_PATH`: Output directory for generated files (default: ../output)
- `EXECUTE_FILE_PATH`: Path to GWMReader.exe parser executable (required for import)
- `REFERENCE_DATA_PATH`: Path to reference_data directory (default: ../reference_data).
  Holds researched, citable reference data: `machines.json` (CAT machine specs,
  matched to telemetry `TypeName` to enrich model haulers), `materials.json` (material
  densities/swell/fill factors — the loose density now feeds the `des_inputs.json`
  material catalog and schedule, converted to kg/m³; swell/fill factor remain reference
  only) and `haul_road_design.json` (haul-road design norms that ground the generated
  DES settings).

### 8.2 Configuration File

`backend/scripts/config.json` contains processing parameters (for the standalone
CLI path; the HTTP export reads its config from the request body):
- `site`: Site name override
- `output_dir`, `machine_templates_path`
- `data_fetching`: `limit`, `sample_interval`
- `road_detection`: `grid_size`, `min_density`, `simplify_epsilon`, `max_node_distance`,
  `merge_tolerance`
- `zone_detection`: `grid_size`, `min_stop_count`
- `simulation`: `sim_time`

## 9. Performance Considerations

1. **Large File Handling**:
   - Files up to 5 GB are supported
   - Chunked reading (64 MB chunks) prevents memory issues
   - Temporary files are cleaned up after processing

2. **Background Processing**:
   - Export operations run in background threads
   - Status polling allows non-blocking UI updates
   - Multiple exports can be queued (one per site)

3. **Database Optimization**:
   - Telemetry data fetching uses `LIMIT` to control dataset size
   - Sample interval reduces data volume while preserving accuracy
   - Indexed queries for site and machine lookups

4. **Spatial Processing**:
   - Grid-based clustering reduces computational complexity
   - Douglas-Peucker simplification reduces road network size
   - DBSCAN clustering efficiently groups zone points

## 10. Security Considerations

1. **File Upload Security**:
   - File names are sanitized using `secure_filename()` to prevent path traversal
   - Temporary directories use random prefixes
   - All temporary files are cleaned up after processing

2. **Input Validation**:
   - File type validation (extension checking)
   - File size limits prevent resource exhaustion
   - Parser output validation (JSON structure checking)

3. **Error Handling**:
   - Errors are logged but sensitive information is not exposed to clients
   - Parser failures return generic error messages
   - Database connection errors are handled gracefully

## 11. Future Enhancements

Long-horizon, platform-level directions (distinct from the near-term, code-specific
items in the [Deferred backlog](#deferred-backlog-forward-looking) below, which is
where active follow-ups live):

1. **Real-time Processing**: WebSocket support for real-time status updates
   (status is currently delivered via Server-Sent Events + a durable job store).
2. **Batch Processing**: Support for processing multiple sites simultaneously
3. **Advanced Analytics**: Additional productivity metrics and visualizations
   (basic operational counters now exposed via `GET /api/metrics`).
4. **Export Formats**: Support for additional simulation formats
5. **Data Validation**: _Partially delivered (E):_ backend input validation now
   rejects out-of-range numeric params and unknown materials with fail-fast HTTP 400.
   Remaining: richer cross-field rules and field-level error reporting.
6. **Performance Optimization**: Parallel processing for large datasets
7. **User Authentication**: Role-based access control _(explicitly out of the current
   hardening scope by request)_
8. **Audit Logging**: Track all import/export operations _(partial substrate exists:
   structured JSON logs + the durable `job_status` store; a true audit trail is future)_

### Hardening status (current codebase)

The five concrete next steps below were implemented and audited (sequence
A → D → B → C → E), followed by the unblocked backlog items F (frontend polish
+ bool guard) and G (per-load-zone material). Each shipped with tests; the
backend suite is green (167 passing + 1 intentional `xfail`, see the deferred
backlog), alongside the frontend Vitest suite.

1. **Reference data activated (A)** — `reference_data/materials.json` loose density
   (kg/m³) now feeds the `des_inputs.json` material catalog, schedule items, and
   load-zone references as one coherent material (default `copper_ore`, selectable
   via the export config's `material` field, validated with HTTP 400 on an unknown
   material). Replaced the hardcoded `DEFAULT_MATERIAL_DENSITY` (retained as fallback).
2. **`simulation_generator.py` decomposed (D)** — split into the `scripts/simgen/`
   package (geometry, loaders, db, zones, roads, routes, specs, operations, model,
   des) behind a re-export facade; dead `core/routes.py` / `core/tile.py` removed.
   The export pipeline was also made deterministic (ordered DB query + sorted set
   iteration), guarded by a strict byte-identical golden test.
3. **Observed-trip-coherent routing (B)** — routes are now restricted to (load,dump)
   pairs with real observed haulage (previously every geometric pair, ~24/25
   fabricated). DES hauler-group numbering fixed to match the hauler `id` basis.
4. **Export UI (C)** — a database-export screen (site picker, material selector,
   config, live SSE progress, downloads) on the existing export API plus a new
   `GET /api/materials`, conforming to the CAT design system.
5. **Production hardening (E)** — durable DuckDB-backed job state (survives restart,
   with startup reconciliation of orphaned jobs), structured JSON logging + a
   `GET /api/metrics` endpoint, backend input validation (numeric bounds + material
   null-guard) as fail-fast 400s, and an import-path structural smoke test on the
   sample captures. (Authentication/RBAC excluded by request.)

### Deferred backlog (forward-looking)

Known open items, with why each is deferred:

1. **Material-schedule collapse — needs HaulSim modeling ground truth (headline
   open decision).** When one hauler observably services several (load,dump) pairs,
   the material schedule currently keeps only one of them (a capacity-1 cap silently
   drops the rest, e.g. 16 observed route pairs → 1 schedule pair on BhpSpence). The
   correct representation — per-route entries (`num_of_hauler` each) vs one hauler
   group with `multiple_routes=true` spanning routes — requires the HaulSim modeling
   answer; a naive fix would instantiate phantom trucks and inflate the simulated
   fleet. A test (`tests/test_routing.py::TestRouteScheduleCoherence`, marked
   `xfail`) documents this and will turn the suite red (forcing a fix) once resolved.
2. **Per-truck tonnage** — use each truck's `payload_tonnes` for exact per-model
   tonnage (density-only today).
3. **Per-load-zone material** — _delivered in Stream G._ Each detected load zone can
   carry its own operator-assigned material via an optional `zone_materials` map
   ({load_zone_id: material_name}), producing a multi-entry `material_properties`
   catalog with coherent per-zone references (ids stable by sorted material name —
   closes B-acc-2). No map → byte-identical to the single-material output. Operators
   assign per zone in the export UI, sourced from the last export's detected zones
   (surfaced via the export-complete event; refine-and-re-export). Unknown material
   value → 400; an unmatched/stale zone id → warning + site default.
4. **Real-capture correctness validation** — beyond the structural smoke test,
   validate the output numbers against known-good HaulSim results (needs ground truth).
5. **Frontend polish** — _delivered in Stream F._ Numeric-input empty-state UX
   (clearable draft string + default-on-empty-blur, no stale value), a shared
   `ExportToggle` component (de-duplicated from the Import and Export panels), and a
   frontend unit-test stack (Vitest + React Testing Library, 7 tests). The backend
   also now rejects boolean values for numeric export params with a 400 before the
   job starts (`isinstance(True, int)` is `True` in Python).
6. **Deprecated `grid_size` / `min_density` config params** — these legacy
   road-detection knobs are not exposed in the frontend `ExportConfig` and are not
   covered by the export-config validation guard. The open question is whether to
   **remove them** (they are superseded) or **validate them if retained**; decide in a
   future config-cleanup pass, not piecemeal.
7. **Cross-reload zone-discovery persistence** — per-load-zone material (Stream G)
   surfaces a site's detected load zones to the frontend via the export-complete event,
   held in session state. The list is lost on a page reload before re-exporting (one
   re-export rediscovers it — the refine-and-re-export loop). Persisting last-export
   zones per site (via the E job_store + a read-only GET) was deliberately deferred;
   revisit only if the loop proves annoying in practice.

Longer-horizon, platform-level directions (auth/RBAC, audit logging, batch/parallel
processing, WebSocket status, additional export formats, richer analytics) live in
[§11 Future Enhancements](#11-future-enhancements) above.
