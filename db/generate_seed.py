#!/usr/bin/env python3
"""
Build the embedded DuckDB database (db/haulsim.duckdb) for the export path.

Geometry/catalog come from db/catalog.py (shared with tools/generate_gwm.py so the
DB and the uploadable .gwm sample describe the same mine).

Path coords are stored in MILLIMETRES (the model generator divides by 1000).
Deterministic (fixed seed). Override the output location with DUCKDB_PATH.

Run with: uv run --script db/generate_seed.py
"""
# /// script
# requires-python = ">=3.14"
# dependencies = ["duckdb>=1.0"]
# ///
import os
import random
import sys

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalog import SITES, SITE_GEO, LANE_W, cycle_legs  # noqa: E402

OUT = os.getenv("DUCKDB_PATH", os.path.join(os.path.dirname(__file__), "haulsim.duckdb"))
SAMPLE_STEP = 5  # `interval` increment; MOD(interval,5)=0 so all rows survive the query

SCHEMA = [
    'CREATE TABLE site ("SiteId" INTEGER, "Site Name" VARCHAR, "SiteNameShort" VARCHAR)',
    'CREATE TABLE machines ("Machine Unique Id" BIGINT, "Machine Id" INTEGER, "Name" VARCHAR, '
    '"TypeName" VARCHAR, "Autonomous" SMALLINT, "Site Name" VARCHAR, "IPAddress" BIGINT)',
    'CREATE TABLE amt_cycleprodinfo ("cycleProdInfoHandle" BIGINT, "Machine Unique Id" BIGINT, '
    '"segmentId" BIGINT, "cycleId" BIGINT)',
    'CREATE TABLE amt_cycleprodinfo_handle ("cycleProdInfoHandle" BIGINT, "interval" INTEGER, '
    '"pathEasting" DOUBLE, "pathNorthing" DOUBLE, "pathElevation" DOUBLE, "expectedSpeed" DOUBLE, '
    '"actualSpeed" DOUBLE, "pathBank" DOUBLE, "pathHeading" DOUBLE, "leftWidth" DOUBLE, '
    '"rightWidth" DOUBLE, "payloadPercent" INTEGER)',
]


def emit_handle(rows_cpi, rows_h, handle, muid, seg_id, cyc_id, points):
    rows_cpi.append((handle, muid, seg_id, cyc_id))
    iv = 0
    for p in points:
        rows_h.append((
            handle, iv,
            # coords -> millimetres
            round(p["e"] * 1000), round(p["n"] * 1000), round(p["z"] * 1000),
            round(p["es"], 2), round(p["asp"], 2),
            round(p["bank"], 2), p["hdg"],
            LANE_W, LANE_W, int(p["pl"]),
        ))
        iv += SAMPLE_STEP


def main():
    rng = random.Random(42)
    rows_site, rows_mach, rows_cpi, rows_h = [], [], [], []
    mid = 1001            # sequential Machine Id
    muid = 208188400      # Machine Unique Id base
    handle = 5000000      # cycleProdInfoHandle base
    seg = 1440799000      # segmentId base (GPS-epoch-ish)
    cyc = 70000           # cycleId base

    for site_id, site_name, short, machines, n_cycles in SITES:
        rows_site.append((site_id, site_name, short))
        geo = SITE_GEO[site_id]
        for name, mtype, auto, ip in machines:
            muid += 1
            mid += 1
            rows_mach.append((muid, mid, name, mtype, auto, site_name, ip))
            for _ in range(n_cycles):
                cyc += 1
                for leg in cycle_legs(geo, rng):   # 4 segments/handles per cycle
                    handle += 1
                    seg += 1
                    emit_handle(rows_cpi, rows_h, handle, muid, seg, cyc, leg)

    if os.path.exists(OUT):
        os.remove(OUT)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    con = duckdb.connect(OUT)
    for ddl in SCHEMA:
        con.execute(ddl)
    con.executemany('INSERT INTO site VALUES (?,?,?)', rows_site)
    con.executemany('INSERT INTO machines VALUES (?,?,?,?,?,?,?)', rows_mach)
    con.executemany('INSERT INTO amt_cycleprodinfo VALUES (?,?,?,?)', rows_cpi)
    con.executemany(
        'INSERT INTO amt_cycleprodinfo_handle VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', rows_h)
    con.close()

    print(f"Wrote {OUT}")
    print(f"  sites={len(rows_site)} machines={len(rows_mach)} "
          f"cycleprodinfo={len(rows_cpi)} telemetry_points={len(rows_h)}")


if __name__ == "__main__":
    main()
