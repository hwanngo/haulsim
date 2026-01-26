"""Deterministic full-pipeline export for behaviour-preservation testing (sub-project D).

Runs process_site on a fixed seeded site with a fixed config and writes
model.json / des_inputs.json.gz / ledger.json.gz. After the D-0 determinism fix
the pipeline is byte-deterministic on identical input (no time/uuid/random; set
iteration ordered), so the output is a golden fixture: post-D output must be
byte-identical to the captured baseline.
"""

import json
import gzip
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))  # backend/tests/golden
_BACKEND = os.path.dirname(os.path.dirname(_HERE))  # backend
_ROOT = os.path.dirname(_BACKEND)  # repo root
for _p in (_ROOT, _BACKEND, os.path.join(_BACKEND, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import simulation_generator as sg  # noqa: E402

SITE = "BhpSpence"
CONFIG = dict(
    limit=20000,
    sample_interval=5,
    simplify_epsilon=5.0,
    max_node_distance=500.0,
    merge_tolerance=15.0,
    zone_grid_size=10.0,
    zone_min_stops=20,
    sim_time=480,
)

# Multi-material baseline paths and zone assignment.
# BhpSpence detects 5 load zones with ids [1, 2, 3, 4, 5] (sorted).
# We assign iron_ore to the second sorted id (2) and leave the rest as the
# site default (copper_ore).  Using the second zone — not the first — keeps
# the single-material golden (which covers all zones with copper_ore) cleanly
# separate: the multi-material fixture has exactly one zone that differs.
MULTI_BASELINE_PATH = os.path.join(_HERE, "baseline_multi_material.json")
MULTI_ZONE_MATERIALS = {2: "iron_ore"}


def seed_available():
    """True if the DuckDB seed needed for the DB-export path is present."""
    try:
        conn = sg.get_connection()
        cur = conn.cursor()
        return any(s.get("site_name") == SITE for s in sg.fetch_sites(cur))
    except Exception:
        return False


def export_to(out_dir, zone_materials=None):
    """Run the full export for SITE into out_dir. Returns {kind: path}."""
    os.makedirs(out_dir, exist_ok=True)
    conn = sg.get_connection()
    cur = conn.cursor()
    machines = sg.fetch_machines(cur, SITE)
    templates = sg.load_machine_templates()
    machines_list = sg.load_machines_list()
    return sg.process_site(
        cursor=cur,
        site_name=SITE,
        machines=machines,
        output_dir=out_dir,
        machine_templates=templates,
        machines_list=machines_list,
        output_base_name="golden",
        zone_materials=zone_materials,
        **CONFIG,
    )


def read_export(out_dir):
    """Load the three output documents from an export dir (decompressing .gz)."""
    model = json.load(open(os.path.join(out_dir, "golden_model.json")))
    des = json.load(gzip.open(os.path.join(out_dir, "golden_des_inputs.json.gz")))
    ledger = json.load(gzip.open(os.path.join(out_dir, "golden_ledger.json.gz")))
    return {"model": model, "des_inputs": des, "ledger": ledger}


def generate_multi():
    """Generate and write the multi-material golden baseline (baseline_multi_material.json)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        export_to(d, zone_materials=MULTI_ZONE_MATERIALS)
        docs = read_export(d)
    content = json.dumps(docs, sort_keys=True, indent=2)
    with open(MULTI_BASELINE_PATH, "w") as f:
        f.write(content)
    print("Written:", MULTI_BASELINE_PATH)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate golden fixtures.")
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Generate the multi-material baseline instead of the single-material baseline.",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Output directory for single-material baseline (default: tests/golden/baseline/).",
    )
    args = parser.parse_args()

    if args.multi:
        generate_multi()
    else:
        out = args.output_dir or os.path.join(_HERE, "baseline")
        result = export_to(out)
        print("RESULT:", result)
