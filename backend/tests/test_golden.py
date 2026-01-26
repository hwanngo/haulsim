"""Strict behaviour-preservation gate for sub-project D (decomposition).

After D-0 the export is byte-deterministic, so behaviour preservation is a simple
strict comparison: regenerate the full export from the current code and assert it
equals the committed golden fixture (`tests/golden/baseline.json`, canonical
sorted-key JSON of model + des_inputs + ledger). Any value/structural change from
the decomposition fails this test. Self-skips if the DuckDB seed is absent.
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

_FIXTURE = os.path.join(os.path.dirname(__file__), "golden", "baseline.json")


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestGoldenBehaviorPreserved(unittest.TestCase):
    def test_export_matches_committed_golden(self):
        with tempfile.TemporaryDirectory() as d:
            gg.export_to(d)
            docs = gg.read_export(d)
        current = json.dumps(docs, sort_keys=True, indent=2)
        with open(_FIXTURE) as f:
            golden = f.read()
        self.assertEqual(
            current,
            golden,
            "Full export differs from the committed golden fixture — a behaviour "
            "change leaked into the decomposition (or the determinism regressed). "
            "Inspect the diff; do NOT blindly re-capture the golden.",
        )


if __name__ == "__main__":
    unittest.main()
