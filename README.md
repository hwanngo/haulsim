# HaulSim - AMT Cycle Workbench

> **Status: Proof of Concept.** This is a working PoC that demonstrates the full
> telemetry-to-simulation pipeline end to end. Use it today as **educational /
> reference material** — it is not production-hardened. The codebase is modular by
> design, so the missing production concerns (see [Project status](#project-status))
> can be layered on incrementally. New to the domain? Start with the [Glossary](#glossary).

Web application that reads AMT haul-truck telemetry and generates simulation files
(road-network model, DES inputs, and an events ledger). Two ingestion paths:

- **Export** — read telemetry from the database for a site and generate files.
- **Import** — upload a ZIP of raw gateway captures, parse them, and generate files.

> For the full architecture and business logic (import/export flows, cycle/zone/road
> detection, loss analysis, API, validations), see
> [`docs/application_architecture.md`](docs/application_architecture.md). For the
> generated-file formats, see [`docs/`](docs/README.md).

## Purpose

Autonomous Mining Trucks (AMTs) constantly emit **telemetry** — GPS position, speed,
payload, and reason codes — as they haul material around a mine. Turning that raw
stream into something a simulation can use is fiddly: you have to parse the captures,
reconstruct the haul road network, work out where trucks load and dump, slice the
data into cycles, and account for time lost to speed limits.

This app does that end to end. From telemetry it produces the inputs a **discrete-event
simulation (DES)** needs: a road-network **model** (nodes, roads, load/dump zones,
routes, machines), a **DES inputs** file, and an **events ledger**. A downstream
simulator can then replay operations and measure cycle productivity.

It is aimed at engineers and students who want to see, concretely, how messy field
telemetry becomes a clean simulation model — the parsing, the spatial road/zone
detection, the cycle and loss analysis, and the file formats involved.

## Project status

**This is a proof of concept**, not a production system. It runs the whole pipeline on
realistic (synthetic) data and works well as a **learning and reference** codebase. It
can be grown into a production-ready tool by adding the pieces it deliberately leaves
out today:

- **Authentication & authorization** — endpoints are currently open.
- **Validation against real data** — it ships a cross-platform clone of the proprietary
  `GWMReader` and synthetic samples; real captures are not validated.
- **Durable, scalable job state** — job state survives restarts via `backend/job_store.py` (DuckDB-backed, degrades gracefully to in-memory), but is still single-process.
- ~~**Decomposition of the processing core**~~ — shipped: the generator is now the `backend/scripts/simgen/` package; `simulation_generator.py` is a thin facade.
- **Operational hardening** — basic observability/metrics are in (`backend/obs.py`, `GET /api/metrics`), but broader test coverage and production-grade monitoring remain to-do.

The architecture (clear ingestion paths, a shared data catalog, a pluggable parser, a
self-contained frontend) is intentionally modular so these can be layered on without a
rewrite.

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Python **3.14**, **Litestar** (ASGI) served by **granian**, managed with **uv** (`backend/pyproject.toml`) |
| Frontend | React 19 + **TypeScript** + **Vite** + **Chakra UI v3**, managed with **pnpm** (Node **22**) |
| Database | **DuckDB** (embedded, file-based) — no DB server/container |
| Parser | `GWMReader.exe` — a cross-platform Python clone of the proprietary parser |

## Structure

```
.
├── backend/                 # Litestar API + all processing logic
│   ├── app.py               # Thin controller wiring (~62 lines): mounts api/ controllers
│   ├── api/                 # Resource-oriented HTTP controllers
│   │   ├── jobs.py          # Shared job machinery (status stores, SSE, validation, helpers)
│   │   ├── exports.py       # ExportController (/api/exports)
│   │   ├── imports.py       # ImportController (/api/imports)
│   │   └── system.py        # SystemController (/api/sites, /materials, /health, /metrics)
│   ├── pyproject.toml       # deps (uv); creates backend/.venv
│   ├── Dockerfile           # backend image (Python 3.14 + uv)
│   ├── core/                # Reader, Cycle, Segment, gateway parser/converter, db_config
│   ├── scripts/             # simulation_generator.py (thin facade) + simgen/ package
│   │   └── simgen/          # constants, geometry, loaders, db, zones, roads, routes, specs, operations, model, des
│   ├── simulation_analysis/ # GPS -> events conversion
│   ├── job_store.py         # durable job state (DuckDB-backed, degrades to in-memory)
│   ├── obs.py               # JSON event logging + in-process metrics
│   └── tests/               # pytest suite
├── frontend/                # React + TypeScript + Vite + Chakra UI (pnpm)
│   ├── index.html, vite.config.ts, tsconfig.json
│   ├── Dockerfile, nginx.conf # production image (nginx serves build, proxies /api)
│   └── src/                 # App.tsx, system.ts (theme), types.ts; components/ (ImportButton, ExportPanel, ExportToggle, AboutModal)
├── db/                      # embedded DuckDB
│   ├── generate_seed.py     # builds db/haulsim.duckdb (realistic telemetry)
│   └── catalog.py           # shared sites/machines/geometry (seed + .gwm sample)
├── executables/GWMReader.exe # cross-platform parser clone
├── tools/generate_gwm.py    # builds uploadable .gwm import samples (sample_data/)
├── reference_data/          # researched, citable real-world data
│   ├── machines.json        # CAT machine specs (payload, drive, fuel, tyres) -> enriches model
│   ├── materials.json       # bulk material densities / swell / bucket fill factors
│   └── haul_road_design.json # haul-road norms (grade, rolling resistance, traction, speeds)
├── docs/                    # architecture, design system, generated-file specs
├── docker-compose.yml       # full stack: backend + frontend (DuckDB baked in)
└── Makefile                 # run / seed / up / down / ...
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (backend), with Python 3.14 available
- [pnpm](https://pnpm.io/) and Node.js 22+ (frontend)
- Docker (OrbStack / Docker Desktop) — only for the full-stack containers (`make up`);
  the embedded DuckDB needs no server

## Quick start

```bash
make install      # backend deps (uv) + frontend deps (pnpm)
make run          # builds the DuckDB seed, then backend :5001 + frontend :3000
# open http://localhost:3000
```

Then either:
- **Import:** drag `sample_data/import_sample_ESC.zip` onto the upload card (run
  `make gwm-sample` first if it isn't there), or
- **Export:** call the export API for a seeded site (`BhpEscondida`, `BhpSpence`,
  or `CatTinajaHills`).

### Make targets

| Target | Description |
|--------|-------------|
| `make seed` | (Re)build the embedded DuckDB `db/haulsim.duckdb` |
| `make gwm-sample` | (Re)generate uploadable `.gwm` samples; pass `ARGS="--cycles 20 --site ESC"` |
| `make install` | Install backend (uv) + frontend (pnpm) deps |
| `make run` / `make dev` | Run backend + frontend together |
| `make backend` / `make frontend` | Run one side (override port with `PORT=...`) |

### Manual run (without make)

```bash
# Backend (uv) — port aligns with the frontend proxy
cd backend && PORT=5001 uv run python app.py

# Frontend (pnpm) — Vite dev server, proxies /api -> :5001
cd frontend && pnpm dev
```

## The parser clone (`GWMReader.exe`)

The production parser is a proprietary Windows binary. This repo ships a
cross-platform **Python clone** at `executables/GWMReader.exe` that reproduces its
interface (`--sitename=`, one `--files=` per path, JSON to stderr) so the Import
flow works on any OS. It reads a readable `.gwm` clone format (`|`-delimited, 24
fields per line; see the file header). `make gwm-sample` generates valid samples.
Point `EXECUTE_FILE_PATH` at the real binary instead to use production captures.

## Database

`make seed` builds an embedded **DuckDB** file (`db/haulsim.duckdb`) with
tables `site`, `machines`, `amt_cycleprodinfo`, `amt_cycleprodinfo_handle`, holding
realistic haul-cycle telemetry for an all-Caterpillar fleet (3 sites, 18 trucks
spanning the CAT 770G–798 AC range). There is no DB server: the Export path opens
the file read-only. Coordinates are stored in millimetres (the backend divides by
1000). Relocate the file with `DUCKDB_PATH` in `backend/.env`.

## Sample data

Two generators feed the two ingestion paths, and **both read the same mine
geometry from `db/catalog.py`** (sites, machines, zone/road layout) so the DB and
the upload sample describe the same world:

| Generator | Feeds | Output | Units |
|-----------|-------|--------|-------|
| `db/generate_seed.py` | **Export** path (DB) | `db/haulsim.duckdb` | coords in **mm** |
| `tools/generate_gwm.py` | **Import** path (upload) | `sample_data/import_sample_<SHORT>.zip` | coords in **metres** |

```bash
make seed                                   # rebuild the embedded DuckDB database
make gwm-sample                             # regenerate both upload sample ZIPs

# Size / customize the upload sample (Typer CLI; uv installs deps in an isolated env):
uv run --script tools/generate_gwm.py --help
uv run --script tools/generate_gwm.py --cycles 20            # more telemetry per machine
uv run --script tools/generate_gwm.py --site ESC --seed 7    # one site, custom seed
make gwm-sample ARGS="--cycles 20 --site ESC"                # same, via make
```

`--cycles` is the main size knob (haul cycles per machine → number of samples);
output is deterministic for a given `--seed`. `make run` / `make backend` rebuild
the DuckDB seed automatically (the `seed` prerequisite); `make up` bakes a fresh
copy into the backend image at build time. To change sites, machines, or layout for
either path, edit `db/catalog.py` and regenerate both.

The fleet is **all-Caterpillar**. Real per-model specs (payload, drive, engine,
fuel burn, tyres, operating weight) live in
[`reference_data/machines.json`](reference_data/machines.json); the model
generator matches each truck's `TypeName` (e.g. `Cat 793F CMD`) to its spec and copies
it into the generated model's machine list. Two more researched datasets sit alongside:
[`materials.json`](reference_data/materials.json) (ore/overburden densities, swell, fill
factors) and [`haul_road_design.json`](reference_data/haul_road_design.json) (grade,
rolling-resistance, traction, and speed-limit norms that ground the generated DES
settings). Site elevations and haul grades in `db/catalog.py` are scaled to the real
mines. All of this data cites public sources (Cat spec sheets / Performance Handbook,
US Bureau of Mines and mine haul-road design guidelines).

## API Endpoints

### GET `/api/sites`
List available sites (from the database).

### GET `/api/materials`
List available bulk materials from `reference_data/materials.json`.

### GET `/api/health`
Health check.

### GET `/api/metrics`
Return a snapshot of in-process metrics (counters, observations) as JSON.

### POST `/api/exports` → `202` + `Location: /api/exports/{site_name}`
Start an export for a site. Body: `{"site_name": "...", "config": {...}}`. The `config`
object accepts a `material` name (global default), a `zone_materials` map (per-load-zone
material override, keyed by zone ID), and numeric tuning params (grid sizes, tolerances, etc.).
Returns `202 Accepted` with a `Location` header pointing to the job resource.
Concurrent export of the same site returns `409 Conflict`.

### GET `/api/exports/{site_name}`
Poll the export job state (status, progress, message, files, load_zones).
Status values: `idle`, `processing`, `completed`, `interrupted`, `error`.

### GET `/api/exports/{site_name}/events` (SSE)
Stream live export progress via Server-Sent Events. The export-complete event carries
`load_zones: [{id, name, hint}]` for per-zone material assignment on re-export.

### GET `/api/exports/{site_name}/files/{file_type}`
Download a generated file. `file_type`: `model`, `des_inputs`, `ledger`, `routes_excel`
(`des_inputs` and `ledger` are gzipped).

### POST `/api/imports` → `202` + `Location: /api/imports/{name}`
Upload one `.zip` of raw gateway files (`multipart/form-data`). With `export=true`
it also generates simulation files after parsing. Returns `202 Accepted` with a
`Location` header pointing to the job resource. The `{name}` key is the
`output_base_name` form field if supplied, otherwise `site_name`.

### GET `/api/imports/{name}`
Poll the import+export job state (same shape as the export job resource).

### GET `/api/imports/{name}/events` (SSE)
Stream live import+export progress via Server-Sent Events.

### GET `/api/imports/{name}/files/{file_type}`
Download a file generated by the import+export flow. Same `file_type` values as the
export download endpoint.

## Environment variables

Backend config lives in `backend/.env` (copy from `backend/.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DUCKDB_PATH` | Embedded DuckDB database file | `../db/haulsim.duckdb` |
| `EXECUTE_FILE_PATH` | Path to the parser executable (file) | `../executables/GWMReader.exe` |
| `OUTPUT_PATH` / `REFERENCE_DATA_PATH` / `TEMP_DIR` | Output dir / example data / temp dir | `../output` / `../reference_data` / system temp |
| `PORT` / `HOST` | Server bind port / address | `5001` / `127.0.0.1` |
| `CORS_ORIGINS` | Allowed frontend origins (comma-separated) | `http://localhost:3000,http://127.0.0.1:3000` |
| `MAX_UPLOAD_MB` / `MAX_DECOMPRESSED_MB` | Upload + zip-bomb limits | `5120` / `20480` |

Compose reads optional tunables from a root `.env` (see `.env.docker.example`); no DB
credentials are needed since the database is an embedded file baked into the image.
Both `.env` files are gitignored.

## Tests

```bash
cd backend && uv run pytest        # or: make test
```

## Glossary

| Term | Meaning |
|------|---------|
| **AMT** | Autonomous Mining Truck — a driverless haul truck that emits telemetry. |
| **Telemetry** | Time-stamped sensor data per truck: position (easting/northing/elevation), speed, payload, heading, and reason codes. |
| **Cycle** | One full haul loop: load → travel full → dump → travel empty. |
| **Segment** | A contiguous slice of a cycle in one state (e.g. travelling full, spotting at the load zone). |
| **Load zone (source)** | Area where a truck is loaded; payload goes empty → full. |
| **Dump zone (sink)** | Area where a truck dumps its load; payload goes full → empty. |
| **Node / road** | The haul-road network detected from trajectories; nodes are key points, roads connect them. |
| **Route** | An ordered path of roads a truck takes between a load and a dump zone. |
| **Model** | The generated road-network file: nodes, roads, zones, routes, machines (`*_model.json`). |
| **DES** | Discrete-Event Simulation — models operations as a sequence of timed events. |
| **DES inputs** | The configuration file that feeds the simulator (`*_des_inputs.json.gz`). |
| **Events ledger** | Chronological list of state-change events derived from the telemetry (`*_ledger.json.gz`). |
| **ASLR** | Autonomous Speed Limit Reason — a code explaining why a truck was slowed; used for loss analysis. |
| **Loss analysis** | Comparing actual vs expected time per segment to quantify productivity loss by reason. |
| **GWM / `.gwm`** | Raw gateway-message capture file produced in the field. |
| **GWMReader** | The parser that turns `.gwm` captures into structured records (this repo ships a cross-platform clone). |
| **Export path** | Generate simulation files from telemetry already in the database. |
| **Import path** | Upload a ZIP of `.gwm` captures, parse them, then generate simulation files. |
| **SSE** | Server-Sent Events — the one-way stream the backend uses to push live import/export progress to the UI. |
| **Site** | A mine (e.g. `BhpEscondida`, `BhpSpence`, `CatTinajaHills`); telemetry and machines belong to a site. |

## Notes

- Export/import job state is persisted to a DuckDB file (`output/jobs.duckdb`) via `job_store.py` and survives restarts; the backend is still single-process.
- The backend binds `127.0.0.1` by default; set `HOST=0.0.0.0` only for trusted
  local dev or container use.
