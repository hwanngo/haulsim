"""
tests/test_obs.py — Tests for backend/obs.py (Task E-2: observability).

Coverage:
  (a) GET /api/metrics returns 200 JSON with expected keys (>=0 values)
  (b) metrics.incr("export_count") is reflected in snapshot()
  (c) log_event() emits a valid JSON line to stderr with the expected fields
"""

import io
import json
import logging
import os
import sys
import unittest

# Ensure both the backend dir and project root are importable
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
PROJECT_ROOT = os.path.normpath(os.path.join(BACKEND_DIR, ".."))
for p in (BACKEND_DIR, PROJECT_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import obs as obs_module  # noqa: E402  (obs.py in backend/)


# ---------------------------------------------------------------------------
# (b) Unit tests for the _Metrics object
# ---------------------------------------------------------------------------


class TestMetricsUnit(unittest.TestCase):
    def setUp(self):
        # Use a fresh _Metrics instance for each test so state is isolated.
        self.m = obs_module._Metrics()

    def test_snapshot_has_required_keys(self):
        """snapshot() always contains the canonical keys, even before any updates."""
        snap = self.m.snapshot()
        for key in (
            "import_count",
            "export_count",
            "export_failures",
            "export_duration_last",
            "records_processed",
        ):
            self.assertIn(key, snap, f"Missing key: {key}")

    def test_initial_counters_are_zero(self):
        snap = self.m.snapshot()
        for key in (
            "import_count",
            "export_count",
            "export_failures",
            "records_processed",
        ):
            self.assertEqual(snap[key], 0, f"{key} should start at 0")

    def test_incr_export_count(self):
        """After incr('export_count'), snapshot reflects the new value."""
        self.m.incr("export_count")
        snap = self.m.snapshot()
        self.assertEqual(snap["export_count"], 1)

    def test_incr_multiple(self):
        self.m.incr("export_count", 3)
        self.assertEqual(self.m.snapshot()["export_count"], 3)

    def test_incr_ad_hoc_counter(self):
        """Incrementing an ad-hoc counter (not in canonical list) works."""
        self.m.incr("custom_counter")
        self.assertEqual(self.m.snapshot()["custom_counter"], 1)

    def test_observe_updates_gauge(self):
        self.m.observe("export_duration_last", 123.4)
        snap = self.m.snapshot()
        self.assertAlmostEqual(snap["export_duration_last"], 123.4)

    def test_observe_overwrites_previous(self):
        self.m.observe("export_duration_last", 10.0)
        self.m.observe("export_duration_last", 20.0)
        self.assertAlmostEqual(self.m.snapshot()["export_duration_last"], 20.0)

    def test_snapshot_is_copy(self):
        """Mutating the returned snapshot dict doesn't affect the store."""
        snap1 = self.m.snapshot()
        snap1["export_count"] = 999
        snap2 = self.m.snapshot()
        self.assertEqual(snap2["export_count"], 0)

    def test_thread_safety(self):
        """Concurrent incr calls from multiple threads produce the correct total."""
        import threading

        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(100):
                self.m.incr("export_count")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.m.snapshot()["export_count"], 1000)


# ---------------------------------------------------------------------------
# (c) Unit tests for log_event() — JSON line emitted to stderr
# ---------------------------------------------------------------------------


class TestLogEvent(unittest.TestCase):
    def _capture_log_event(self, event: str, **fields) -> dict:
        """Call log_event and capture the emitted JSON via a StringIO handler."""
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(obs_module._JsonFormatter())

        logger = logging.getLogger("amt")
        logger.addHandler(handler)
        try:
            obs_module.log_event(event, **fields)
        finally:
            logger.removeHandler(handler)

        output = buf.getvalue().strip()
        self.assertTrue(output, "log_event produced no output")
        return json.loads(output)

    def test_log_event_is_valid_json(self):
        """log_event emits a line parseable by json.loads."""
        data = self._capture_log_event("test_event")
        self.assertIsInstance(data, dict)

    def test_log_event_has_required_fields(self):
        """Emitted JSON contains ts, level, and event fields."""
        data = self._capture_log_event("my_test_event")
        self.assertIn("ts", data)
        self.assertIn("level", data)
        self.assertIn("event", data)
        self.assertEqual(data["event"], "my_test_event")

    def test_log_event_extra_fields_present(self):
        """Extra keyword arguments appear as top-level fields in JSON."""
        data = self._capture_log_event(
            "export_start",
            site="TestSite",
            job="export",
            stage="init",
        )
        self.assertEqual(data["site"], "TestSite")
        self.assertEqual(data["job"], "export")
        self.assertEqual(data["stage"], "init")

    def test_log_event_duration_ms(self):
        data = self._capture_log_event("export_done", duration_ms=500)
        self.assertEqual(data["duration_ms"], 500)

    def test_log_event_none_fields_omitted(self):
        """Fields with None values are stripped from the JSON line."""
        data = self._capture_log_event("sparse_event")
        # The canonical optional fields should be absent when not supplied
        self.assertNotIn("site", data)
        self.assertNotIn("job", data)
        self.assertNotIn("stage", data)
        self.assertNotIn("duration_ms", data)


# ---------------------------------------------------------------------------
# (a) HTTP endpoint test: GET /api/metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Import app and create a TestClient once for the whole class."""
        from litestar.testing import TestClient
        import app as app_module

        cls.app_module = app_module
        cls.client = TestClient(app=app_module.app)

    def test_metrics_endpoint_200(self):
        """GET /api/metrics returns 200."""
        resp = self.client.get("/api/metrics")
        self.assertEqual(resp.status_code, 200)

    def test_metrics_endpoint_is_json(self):
        resp = self.client.get("/api/metrics")
        data = resp.json()
        self.assertIsInstance(data, dict)

    def test_metrics_endpoint_has_required_keys(self):
        """Response JSON contains the canonical metric keys with non-negative counts."""
        resp = self.client.get("/api/metrics")
        data = resp.json()
        for key in (
            "import_count",
            "export_count",
            "export_failures",
            "records_processed",
        ):
            self.assertIn(key, data, f"Missing key: {key}")
            self.assertGreaterEqual(data[key], 0, f"{key} must be >= 0")

    def test_metrics_export_duration_last_key_present(self):
        """export_duration_last key is always present (may be null/None)."""
        resp = self.client.get("/api/metrics")
        data = resp.json()
        self.assertIn("export_duration_last", data)


if __name__ == "__main__":
    unittest.main()
