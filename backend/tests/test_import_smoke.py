"""E Task 6: import-path structural smoke test on the sample captures.

Runs the full import pipeline (parse GWM -> convert -> process_site) on each
sample_data/import_sample_*.zip and asserts the produced model/des/ledger are
STRUCTURALLY valid (expected keys, non-empty where required, referential
integrity) -- NOT value-correctness (that needs HaulSim ground truth). The import
path is the webapp's primary flow and is deterministic post-D-0.

Self-skips if GWMReader.exe is absent.
"""

import gzip
import json
import os
import sys
import tempfile
import unittest
import zipfile

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (
    BACKEND_DIR,
    os.path.normpath(os.path.join(BACKEND_DIR, "..")),
    os.path.join(BACKEND_DIR, "scripts"),
):
    sys.path.insert(0, _p)

import simulation_generator as sg  # noqa: E402
from backend.core.gateway_parser_wrapper import parse_gateway_files  # noqa: E402
from backend.core.gateway_data_converter import (  # noqa: E402
    process_parser_output,
    convert_imported_records_to_telemetry,
)

_ROOT = os.path.normpath(os.path.join(BACKEND_DIR, ".."))
_GWM_EXE = os.path.abspath(os.path.join(_ROOT, "executables", "GWMReader.exe"))
_SAMPLE_DIR = os.path.join(_ROOT, "sample_data")
_SAMPLES = ["import_sample_ESC.zip", "import_sample_SPE.zip", "import_sample_TJH.zip"]


def _run_import(zip_path, out_dir):
    with tempfile.TemporaryDirectory() as ex:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(ex)
        files = sorted(os.path.join(r, f) for r, _, fs in os.walk(ex) for f in fs)
        site = os.path.splitext(os.path.basename(zip_path))[0]
        parsed = parse_gateway_files(site, files, parser_exe_path=_GWM_EXE)
        assert "error" not in parsed, f"parse failed: {parsed.get('error')}"
        records = process_parser_output(parsed)
        telemetry = convert_imported_records_to_telemetry(parsed, records)
        assert telemetry, "no telemetry produced from sample"
        result = sg.process_site(
            cursor=None,
            site_name=site,
            machines={},
            telemetry_data=list(telemetry),
            coordinates_in_meters=True,
            output_dir=out_dir,
            output_base_name="smoke",
            machine_templates=sg.load_machine_templates(),
            machines_list=sg.load_machines_list(),
            sim_time=480,
        )
    model = json.load(open(result["model"]))
    des = json.load(gzip.open(result["des_inputs"]))
    ledger = json.load(gzip.open(result["ledger"]))
    return model, des, ledger


@unittest.skipUnless(os.path.exists(_GWM_EXE), "GWMReader.exe not available")
class TestImportSmoke(unittest.TestCase):
    def _assert_structural(self, model, des, ledger, label):
        # Model: required top-level keys + non-empty core collections.
        for k in ("nodes", "roads", "load_zones", "dump_zones", "routes", "operations"):
            self.assertIn(k, model, f"{label}: model missing '{k}'")
        self.assertTrue(model["nodes"], f"{label}: no nodes")
        self.assertTrue(model["load_zones"], f"{label}: no load zones")
        self.assertTrue(model["dump_zones"], f"{label}: no dump zones")

        # DES: required keys + catalog present.
        for k in ("material_properties", "haulers", "routes", "nodes", "load_zones"):
            self.assertIn(k, des, f"{label}: des missing '{k}'")
        self.assertTrue(des["material_properties"], f"{label}: empty material catalog")

        # Ledger: events present (ledger shape: {status, data:{version, events, summary}}).
        events = (
            ledger.get("data", {}).get("events", []) if isinstance(ledger, dict) else []
        )
        self.assertTrue(events, f"{label}: no ledger events")

        # Referential integrity: every des load-zone material ref resolves to a
        # material_properties key; every schedule hauler_group_id resolves to a hauler id.
        catalog_keys = set(des["material_properties"].keys())
        for lz in des.get("load_zones", []):
            for ref in lz.get("material", []):
                self.assertIn(
                    ref,
                    catalog_keys,
                    f"{label}: load-zone material ref {ref!r} dangling",
                )
        hauler_ids = {h.get("id") for h in des.get("haulers", [])}
        sched = (
            des.get("operations", {})
            .get("material_schedules", {})
            .get("all_material_schedule", [])
        )
        for s in sched:
            for item in s.get("data", []):
                g = item.get("hauler_group_id")
                if g is not None:
                    self.assertIn(
                        g, hauler_ids, f"{label}: schedule hauler_group_id {g} dangling"
                    )

    def test_samples_produce_structurally_valid_output(self):
        ran = 0
        for name in _SAMPLES:
            zip_path = os.path.join(_SAMPLE_DIR, name)
            if not os.path.exists(zip_path):
                continue
            with tempfile.TemporaryDirectory() as out_dir:
                model, des, ledger = _run_import(zip_path, out_dir)
            self._assert_structural(model, des, ledger, name)
            ran += 1
        if ran == 0:
            self.skipTest("no sample zips found to smoke-test")


if __name__ == "__main__":
    unittest.main()
