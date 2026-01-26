"""Permanent guards from sub-project D-0 (determinism prerequisite).

- The full export pipeline must be byte-deterministic on identical input. Set-driven
  iteration previously permuted hauler id/group_id assignment run-to-run; these tests
  stop anyone reintroducing that.
- Material-schedule hauler_group_id references must resolve to real haulers, so a
  deterministic renumber never silently misaligns cross-references.

Both tests use the DB-export path and self-skip if the DuckDB seed is absent.
"""

import json
import os
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))
sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))
sys.path.insert(0, os.path.join(BACKEND_DIR, "tests", "golden"))

import generate_golden as gg  # noqa: E402


def _canon(doc):
    return json.dumps(doc, sort_keys=True)


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestExportDeterminism(unittest.TestCase):
    def test_three_runs_byte_identical(self):
        outs = []
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                sub = os.path.join(d, f"run{i}")
                gg.export_to(sub)
                outs.append(gg.read_export(sub))
        # Each of the three documents must be identical across all three runs.
        for kind in ("model", "des_inputs", "ledger"):
            a, b, c = (_canon(o[kind]) for o in outs)
            self.assertEqual(a, b, f"{kind} differs between run 0 and run 1")
            self.assertEqual(b, c, f"{kind} differs between run 1 and run 2")


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestImportPathDeterminism(unittest.TestCase):
    """The import (provided-telemetry) flow inserts machines from a set; without
    sorted insertion its hauler id/group_id assignment permutes run-to-run. Exercise
    that branch by feeding DB telemetry back in as provided telemetry with machines={}."""

    def test_provided_telemetry_export_is_deterministic(self):
        import simulation_generator as sg

        conn = sg.get_connection()
        cur = conn.cursor()
        machines_db = sg.fetch_machines(cur, gg.SITE)
        tele = sg.fetch_telemetry_data(
            cur, machine_ids=list(machines_db.keys()), limit=20000, sample_interval=5
        )
        tele = list(tele)
        templates = sg.load_machine_templates()
        machines_list = sg.load_machines_list()
        sigs = []
        with tempfile.TemporaryDirectory() as d:
            for i in range(2):
                sub = os.path.join(d, f"imp{i}")
                os.makedirs(sub, exist_ok=True)
                sg.process_site(
                    cursor=None,
                    site_name=gg.SITE,
                    machines={},
                    telemetry_data=list(tele),
                    coordinates_in_meters=False,
                    output_dir=sub,
                    output_base_name="imp",
                    machine_templates=templates,
                    machines_list=machines_list,
                    sim_time=480,
                )
                sigs.append(_canon(_read_named(sub, "imp")))
        self.assertEqual(sigs[0], sigs[1], "import-path export is not deterministic")


def _read_named(out_dir, base):
    import gzip

    model = json.load(open(os.path.join(out_dir, f"{base}_model.json")))
    des = json.load(gzip.open(os.path.join(out_dir, f"{base}_des_inputs.json.gz")))
    ledger = json.load(gzip.open(os.path.join(out_dir, f"{base}_ledger.json.gz")))
    return {"model": model, "des_inputs": des, "ledger": ledger}


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestScheduleReferentialIntegrity(unittest.TestCase):
    def test_schedule_hauler_groups_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            gg.export_to(d)
            docs = gg.read_export(d)

        for kind, id_field in (("model", "group_id"), ("des_inputs", "id")):
            doc = docs[kind]
            haulers = doc.get("haulers", [])
            valid_ids = {h.get(id_field) for h in haulers}
            sched = (
                doc.get("operations", {})
                .get("material_schedules", {})
                .get("all_material_schedule", [])
            )
            refs = {
                item.get("hauler_group_id")
                for s in sched
                for item in s.get("data", [])
                if item.get("hauler_group_id") is not None
            }
            self.assertTrue(refs, f"{kind}: expected schedule hauler_group_id refs")
            dangling = sorted(r for r in refs if r not in valid_ids)
            self.assertEqual(
                dangling,
                [],
                f"{kind}: schedule hauler_group_id refs do not resolve to a hauler "
                f"{id_field}: {dangling} (valid={sorted(v for v in valid_ids if v is not None)})",
            )


if __name__ == "__main__":
    unittest.main()
