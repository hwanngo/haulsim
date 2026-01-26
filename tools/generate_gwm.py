#!/usr/bin/env python3
"""
Generate uploadable .gwm import samples for the AMT Cycle Workbench.

Writes one ZIP per site to sample_data/ (e.g. import_sample_ESC.zip), each
containing one .gwm capture per machine in the readable clone format that
executables/GWMReader.exe understands.

Coords are in METRES and speeds in m/s (the import path uses
coordinates_in_meters=True and multiplies speed by 3.6). Geometry comes from
db/catalog.py so the sample matches the Dockerized DB.

Deterministic. Pure stdlib.

Usage (uv installs typer in an isolated env via the inline script metadata):
    uv run --script tools/generate_gwm.py                 # all sites, default cycle counts
    uv run --script tools/generate_gwm.py --cycles 20     # 20 haul cycles per machine (more data)
    uv run --script tools/generate_gwm.py --site ESC      # just one site
    uv run --script tools/generate_gwm.py --cycles 50 --seed 7 --out /tmp/samples

`--cycles` is the main size knob: total samples per machine =
cycles x (load-stop + haul + dump-stop + return) points. Output is deterministic
for a given --seed (the .gwm contents are identical run-to-run). Run with no
options to reproduce the default sample used by `make gwm-sample`.
"""
# /// script
# requires-python = ">=3.14"
# dependencies = ["typer>=0.12"]
# ///
import os
import random
import sys
import zipfile
from typing import Optional

import typer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "db"))
from catalog import SITES, SITE_GEO, LANE_W, cycle_legs  # noqa: E402

OUT_DIR = os.path.join(ROOT, "sample_data")

# Fixed reason/regulation codes (parity with real captures; see docs).
EXP_SRC, EXP_ASLR, EXP_REG = 5, 5, 0
ACT_SRC, ACT_ASLR, ACT_REG = 58, 31, 0

HEADER = (
    "# AMT gateway message capture (clone format v1) — readable by GWMReader.exe\n"
    "# fields: ip|segmentId|startTime|expElapsed|actElapsed|easting|northing|"
    "elevation|plannedDist|expSpeed|actSpeed|expDesSpeed|actDesSpeed|leftW|rightW|"
    "bank|heading|payload|expSpdSrc|expASLR|expRegMod|actSpdSrc|actASLR|actRegMod\n"
)


def gwm_line(ip, seg, p):
    fields = [
        ip, seg, "",                      # ip, segmentId, startTime (blank -> derived)
        round(p["sec"], 2), round(p["sec"], 2),
        round(p["e"], 2), round(p["n"], 2), round(p["z"], 2),
        5.0,                              # plannedDist (m)
        round(p["es"], 2), round(p["asp"], 2),
        round(p["es"], 2), round(p["asp"], 2),
        LANE_W, LANE_W,
        round(p["bank"], 2), p["hdg"], int(p["pl"]),
        EXP_SRC, EXP_ASLR, EXP_REG, ACT_SRC, ACT_ASLR, ACT_REG,
    ]
    return "|".join("" if f == "" else str(f) for f in fields)


def build_site_zip(site, cycles, rng, out_dir):
    """Write one site's import ZIP. `cycles` overrides the catalog default when set.
    Returns (zip_path, machine_count, sample_count, cycles_used, site_name)."""
    site_id, site_name, short, machines, default_cycles = site
    n_cycles = default_cycles if cycles is None else cycles
    geo = SITE_GEO[site_id]
    zip_path = os.path.join(out_dir, f"import_sample_{short}.zip")
    total_pts = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, mtype, auto, ip in machines:
            lines = [HEADER.rstrip("\n")]
            seg = 1440799000
            for _ in range(n_cycles):
                # Each leg gets its own segmentId so parse_cp1_data sees the
                # empty->full (load/SOURCE) and full->empty (dump/SINK) transitions.
                for leg in cycle_legs(geo, rng):
                    seg += 1
                    for p in leg:
                        lines.append(gwm_line(ip, seg, p))
                        total_pts += 1
            zf.writestr(f"{name}.gwm", "\n".join(lines) + "\n")
    return zip_path, len(machines), total_pts, n_cycles, site_name


_SITE_SHORTS = ", ".join(s[2] for s in SITES)

app = typer.Typer(add_completion=False,
                  help="Generate uploadable .gwm import sample ZIP(s) for the AMT reader.")


@app.command()
def main(
    site: str = typer.Option("all", help=f"Site short code ({_SITE_SHORTS}) or 'all'."),
    cycles: Optional[int] = typer.Option(
        None, min=1,
        help="Haul cycles per machine (default: per-site value from the catalog). "
             "Higher = more telemetry samples."),
    seed: int = typer.Option(42, help="RNG seed for deterministic output."),
    out: str = typer.Option(OUT_DIR, help="Output directory for the ZIP(s)."),
):
    """Write one ZIP per selected site to the output directory."""
    sel = site.upper()
    sites = SITES if sel == "ALL" else [s for s in SITES if s[2].upper() == sel]
    if not sites:
        raise typer.BadParameter(
            f"unknown site '{site}'. Choose from: {_SITE_SHORTS}, or 'all'.", param_hint="--site")

    os.makedirs(out, exist_ok=True)
    rng = random.Random(seed)  # one stream across sites -> stable default output
    grand_total = 0
    for site_tuple in sites:
        zip_path, n_mach, n_pts, n_cyc, site_name = build_site_zip(site_tuple, cycles, rng, out)
        grand_total += n_pts
        typer.echo(f"Wrote {zip_path}  ({n_mach} machines, {n_cyc} cycles/machine, "
                   f"{n_pts} samples, site_name='{site_name}')")
    if len(sites) > 1:
        typer.echo(f"Total: {grand_total} samples across {len(sites)} sites.")


if __name__ == "__main__":
    app()
