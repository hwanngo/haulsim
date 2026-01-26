"""
Tests for app.py audit fixes:

  C1 - import-path DB usage wrapped in try/finally so connection always closes
  H3 - cursors opened with `with connection.cursor()` so they always close
  M1 - user-supplied output_base_name run through secure_filename at API boundary
  M5 - DB-unavailable during the IMPORT path is a loud error, not a silent fallback
"""

import os
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BACKEND_DIR)
# app.py imports as `backend.*`, so the repo root must also be importable.
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))

import app as app_module  # noqa: E402
import backend.api.exports as exports_module  # noqa: E402
import backend.api.imports as imports_module  # noqa: E402
import backend.api.jobs as jobs_module  # noqa: E402


class FakeCursor:
    """Cursor that records close() and supports the context-manager protocol."""

    def __init__(self, raise_on_execute=False):
        self.closed = False
        self.entered = False
        self.exited = False
        self.raise_on_execute = raise_on_execute

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        self.close()
        return False

    def execute(self, *args, **kwargs):
        if self.raise_on_execute:
            raise RuntimeError("boom during execute")

    def fetchall(self):
        return []

    def close(self):
        self.closed = True


class FakeConnection:
    """Connection that records close() and hands out a FakeCursor."""

    def __init__(self, cursor=None):
        self.closed = False
        self._cursor = cursor or FakeCursor()

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class TestC1ConnectionClosed(unittest.TestCase):
    def test_connection_closed_on_cursor_exception(self):
        """C1/H3: an exception mid-query must still close connection AND cursor."""
        cur = FakeCursor(raise_on_execute=True)
        conn = FakeConnection(cursor=cur)

        with mock.patch.object(imports_module, "get_connection", return_value=conn):
            # An IP set is required to reach cursor.execute().
            telemetry = [("10.0.0.1", 100, 1.0, 2.0)]
            with (
                mock.patch.object(
                    imports_module,
                    "convert_imported_records_to_telemetry",
                    return_value=telemetry,
                ),
                mock.patch.object(
                    imports_module,
                    "extract_zones_from_import",
                    return_value=([], []),
                ),
                mock.patch.object(
                    imports_module,
                    "load_machine_templates",
                    return_value={},
                ),
                mock.patch.object(
                    imports_module,
                    "load_machines_list",
                    return_value={},
                ),
                mock.patch.object(
                    imports_module,
                    "process_site",
                    return_value=None,
                ),
            ):
                imports_module.process_import_and_export(
                    site_name="S",
                    parse_result={},
                    records=[],
                    config={},
                    output_base_name="base",
                )

        self.assertTrue(conn.closed, "connection.close() must be called on exception")
        self.assertTrue(cur.closed, "cursor.close() must be called on exception (H3)")


class TestM5DbUnavailable(unittest.TestCase):
    def test_db_unavailable_is_error(self):
        """M5: get_connection() returning None during import => error status."""
        captured = {}

        def fake_set_import_status(name, status, *a, **k):
            captured.setdefault("statuses", []).append(status)

        with (
            mock.patch.object(imports_module, "get_connection", return_value=None),
            mock.patch.object(
                imports_module,
                "convert_imported_records_to_telemetry",
                return_value=[("10.0.0.1", 100, 1.0, 2.0)],
            ),
            mock.patch.object(
                imports_module,
                "extract_zones_from_import",
                return_value=([], []),
            ),
            mock.patch.object(
                imports_module,
                "set_import_status",
                side_effect=fake_set_import_status,
            ),
            mock.patch.object(imports_module, "process_site") as mock_process,
        ):
            imports_module.process_import_and_export(
                site_name="S",
                parse_result={},
                records=[],
                config={},
                output_base_name="base",
            )

        self.assertIn(
            "error",
            captured.get("statuses", []),
            "DB unavailable during import must set an error status",
        )
        mock_process.assert_not_called()


class TestM1SecureFilename(unittest.TestCase):
    def test_output_base_name_sanitized(self):
        """M1: traversal-style output_base_name is sanitized via secure_filename."""
        from litestar.testing import TestClient

        captured = {}

        def fake_thread(target=None, args=(), **kwargs):
            # args order: (site_name, parse_result, records, config,
            #              output_base_name, ...)
            captured["output_base_name"] = args[4]

            class _T:
                daemon = True

                def start(self):
                    pass

            return _T()

        import io as _io
        import zipfile as _zip

        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("f0.dat", b"x")
        buf.seek(0)

        with (
            mock.patch.object(
                imports_module, "parse_gateway_files", return_value={"ok": True}
            ),
            mock.patch.object(
                imports_module, "process_parser_output", return_value=[{"a": 1}]
            ),
            mock.patch.object(
                imports_module.threading, "Thread", side_effect=fake_thread
            ),
            mock.patch.object(imports_module.os.path, "exists", return_value=True),
        ):
            with TestClient(app=app_module.app) as client:
                resp = client.post(
                    "/api/imports",
                    data={
                        "output_base_name": "../../../etc/passwd",
                        "export": "true",
                    },
                    files={"files": ("data.zip", buf, "application/zip")},
                )

        self.assertEqual(resp.status_code, 202, resp.text)
        name = captured.get("output_base_name", "")
        self.assertNotIn("..", name)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)


class TestExportMaterialValidation(unittest.TestCase):
    """Task 4: material validation returns 400 for unknown material names."""

    def setUp(self):
        # export_status is module-global; a prior test's successful POST now
        # leaves the site in "processing" (set synchronously before 202), which
        # would make a later POST to the same site 409 instead of reaching the
        # material/400 path. Clear it so each test starts isolated.
        jobs_module.export_status.clear()

    def test_export_unknown_material_returns_400(self):
        """Unknown material in export config → HTTP 400 listing valid names."""
        from litestar.testing import TestClient

        with TestClient(app=app_module.app) as client:
            resp = client.post(
                "/api/exports",
                json={
                    "site_name": "AnySite",
                    "config": {"material": "unobtainium"},
                },
            )

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("copper_ore", resp.text)

    def test_export_omitted_material_is_not_error(self):
        """Omitted material → default (no 400); background job starts → 202."""
        from litestar.testing import TestClient

        captured = {}

        def fake_thread(target=None, args=(), **kwargs):
            captured["started"] = True

            class _T:
                daemon = True

                def start(self):
                    pass

            return _T()

        with (
            mock.patch.object(
                exports_module, "get_export_status", return_value={"status": "idle"}
            ),
            mock.patch.object(
                exports_module.threading, "Thread", side_effect=fake_thread
            ),
        ):
            with TestClient(app=app_module.app) as client:
                resp = client.post(
                    "/api/exports",
                    json={"site_name": "AnySite"},
                )

        self.assertNotEqual(resp.status_code, 400, resp.text)
        self.assertTrue(
            captured.get("started"), "Background thread should have started"
        )


class TestMaterialsEndpoint(unittest.TestCase):
    """Task 1 (C): GET /api/materials returns the 5 materials with name+display_name."""

    def test_materials_endpoint_lists_materials(self):
        from litestar.testing import TestClient

        with TestClient(app=app_module.app) as client:
            resp = client.get("/api/materials")

        self.assertEqual(resp.status_code, 200, resp.text)
        mats = resp.json()["materials"]
        names = {m["name"] for m in mats}
        self.assertGreaterEqual(
            names,
            {"copper_ore", "iron_ore", "gold_ore", "coal", "overburden"},
        )
        for m in mats:
            self.assertIn("display_name", m, f"missing display_name in {m}")


class TestExportStaleStatusFix(unittest.TestCase):
    """C review #1: a same-site re-export must overwrite a stale 'completed'
    status SYNCHRONOUSLY before the 202 returns, so the SSE first-frame reflects
    the NEW run (not the prior run's completed + old files)."""

    def setUp(self):
        jobs_module.export_status.clear()

    def tearDown(self):
        jobs_module.export_status.clear()

    def test_post_export_overwrites_stale_completed_synchronously(self):
        from litestar.testing import TestClient

        site = "BhpSpence"
        # Simulate a prior completed run leaving stale status + files.
        jobs_module.set_export_status(
            site, "completed", 100, "done", files={"model": "old_model.json"}
        )

        class _NoThread:
            def __init__(self, *a, **k):
                self.daemon = True

            def start(self):
                pass  # do NOT run process_export (would need the DB)

        with mock.patch.object(exports_module.threading, "Thread", _NoThread):
            with TestClient(app=app_module.app) as client:
                resp = client.post(
                    "/api/exports",
                    json={
                        "site_name": site,
                        "config": {"material": "copper_ore"},
                        "export_model": True,
                        "export_simulation": False,
                        "export_routes_excel": False,
                    },
                )

        self.assertEqual(resp.status_code, 202, resp.text)
        status = jobs_module.get_export_status(site)
        self.assertEqual(
            status.get("status"),
            "processing",
            "stale 'completed' status was not overwritten before 202 returned",
        )
        self.assertNotEqual(
            status.get("files"),
            {"model": "old_model.json"},
            "stale files from the prior run leaked into the new run's status",
        )
        # Verify the 202 response carries a Location header pointing to the new resource.
        self.assertEqual(
            resp.headers.get("Location"),
            f"/api/exports/{site}",
            "202 response must include Location header",
        )


class TestExportNumericParamValidation(unittest.TestCase):
    """C-f2: numeric export config params must be validated with 400 fail-fast
    BEFORE the background job starts.  Only params that are PRESENT in the request
    are validated; omitted params use safe defaults and must NOT be rejected.
    """

    def setUp(self):
        # Isolate each test from prior export_status state (avoids 409 conflicts).
        jobs_module.export_status.clear()

    def tearDown(self):
        jobs_module.export_status.clear()

    # ------------------------------------------------------------------ helpers
    def _post_export(self, config, mock_thread=None):
        """POST /api/exports with the given config dict.  Patches threading.Thread
        to a no-op by default so the background job never actually starts."""
        from litestar.testing import TestClient

        class _NoThread:
            daemon = True

            def start(self):
                pass

        thread_factory = mock_thread or (lambda *a, **kw: _NoThread())

        with mock.patch.object(
            exports_module.threading, "Thread", side_effect=thread_factory
        ):
            with TestClient(app=app_module.app) as client:
                return client.post(
                    "/api/exports",
                    json={"site_name": "TestSite", "config": config},
                )

    # ------------------------------------------------------------------ 400 cases
    def test_negative_limit_returns_400(self):
        resp = self._post_export({"limit": -5})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("limit", resp.text.lower())

    def test_zero_limit_returns_400(self):
        resp = self._post_export({"limit": 0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_zero_sample_interval_returns_400(self):
        resp = self._post_export({"sample_interval": 0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_zero_zone_min_stops_returns_400(self):
        resp = self._post_export({"zone_min_stops": 0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_thread_not_started_on_invalid_param(self):
        """When validation fails the background thread must NOT be started."""
        started = []

        class _Sentinel:
            daemon = True

            def start(self):
                started.append(True)

        resp = self._post_export(
            {"limit": -5}, mock_thread=lambda *a, **kw: _Sentinel()
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(started, [], "Thread.start() must NOT be called on 400")

    def test_negative_simplify_epsilon_returns_400(self):
        resp = self._post_export({"simplify_epsilon": -1.0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_negative_max_node_distance_returns_400(self):
        resp = self._post_export({"max_node_distance": 0.0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_negative_merge_tolerance_returns_400(self):
        resp = self._post_export({"merge_tolerance": -0.1})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_negative_zone_grid_size_returns_400(self):
        resp = self._post_export({"zone_grid_size": -10.0})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_negative_sim_time_returns_400(self):
        resp = self._post_export({"sim_time": -1})
        self.assertEqual(resp.status_code, 400, resp.text)

    # ------------------------------------------------------------------ 202 cases
    def test_valid_request_omitted_numeric_params_returns_202(self):
        """Omitting all numeric params uses defaults — must return 202, not 400."""
        started = []

        class _OkThread:
            daemon = True

            def start(self):
                started.append(True)

        resp = self._post_export({}, mock_thread=lambda *a, **kw: _OkThread())
        self.assertEqual(resp.status_code, 202, resp.text)
        self.assertEqual(
            started, [1], "Thread.start() must be called for valid request"
        )

    def test_valid_explicit_params_returns_202(self):
        """Supplying valid (in-range) numeric params must still return 202."""
        resp = self._post_export(
            {
                "limit": 5000,
                "sample_interval": 30,
                "simplify_epsilon": 0.5,
                "max_node_distance": 100.0,
                "merge_tolerance": 0.0,
                "zone_grid_size": 50.0,
                "zone_min_stops": 3,
                "sim_time": 28800,
            }
        )
        self.assertEqual(resp.status_code, 202, resp.text)

    def test_merge_tolerance_zero_is_valid(self):
        """merge_tolerance >= 0 — zero must pass validation."""
        resp = self._post_export({"merge_tolerance": 0.0})
        self.assertEqual(resp.status_code, 202, resp.text)

    def test_zone_min_stops_one_is_valid(self):
        """zone_min_stops >= 1 — value 1 must pass validation."""
        resp = self._post_export({"zone_min_stops": 1})
        self.assertEqual(resp.status_code, 202, resp.text)


class TestExportBoolParamRejection(unittest.TestCase):
    """Item 3 (E review): boolean values for numeric export params must be
    rejected with 400 BEFORE the job starts (Python isinstance(True, int) is
    True so without this guard True would pass as 1).
    """

    def setUp(self):
        # Isolate from prior export_status state (avoid 409 conflicts).
        jobs_module.export_status.clear()

    def tearDown(self):
        jobs_module.export_status.clear()

    def _post_export(self, config):
        from litestar.testing import TestClient

        class _NoThread:
            daemon = True

            def start(self):
                pass

        with mock.patch.object(
            exports_module.threading, "Thread", side_effect=lambda *a, **kw: _NoThread()
        ):
            with TestClient(app=app_module.app) as client:
                return client.post(
                    "/api/exports",
                    json={"site_name": "TestSite", "config": config},
                )

    def test_bool_limit_returns_400(self):
        """{"config": {"limit": true}} must return 400 (not start a job)."""
        resp = self._post_export({"limit": True})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_bool_sample_interval_returns_400(self):
        resp = self._post_export({"sample_interval": True})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_bool_simplify_epsilon_returns_400(self):
        resp = self._post_export({"simplify_epsilon": True})
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_bool_zone_min_stops_returns_400(self):
        resp = self._post_export({"zone_min_stops": False})
        self.assertEqual(resp.status_code, 400, resp.text)


class TestZoneMaterialsValidation(unittest.TestCase):
    """G: zone_materials VALUES are validated (unknown material -> 400 before job).
    KEYS are not validated here (load zones unknown until detection runs)."""

    def setUp(self):
        jobs_module.export_status.clear()

    def tearDown(self):
        jobs_module.export_status.clear()

    def _post(self, zone_materials):
        from litestar.testing import TestClient

        class _NoThread:
            daemon = True

            def start(self):
                pass

        with mock.patch.object(
            exports_module.threading, "Thread", side_effect=lambda *a, **kw: _NoThread()
        ):
            with TestClient(app=app_module.app) as client:
                return client.post(
                    "/api/exports",
                    json={
                        "site_name": "TestSite",
                        "config": {
                            "material": "copper_ore",
                            "zone_materials": zone_materials,
                        },
                    },
                )

    def test_unknown_material_value_returns_400(self):
        resp = self._post({"1": "unobtainium"})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertIn("unobtainium", resp.text)

    def test_known_material_values_accepted(self):
        resp = self._post({"1": "copper_ore", "2": "iron_ore"})
        self.assertEqual(resp.status_code, 202, resp.text)

    def test_stale_key_is_accepted_at_api_boundary(self):
        # A key that may not match a detected zone is NOT a 400 (warn+default at runtime).
        resp = self._post({"9999": "iron_ore"})
        self.assertEqual(resp.status_code, 202, resp.text)

    def test_non_int_key_returns_400(self):
        """A non-integer zone_materials key must return 400 (coverage gap)."""
        resp = self._post({"abc": "iron_ore"})
        self.assertEqual(resp.status_code, 400, resp.text)


class TestLoadZonesSummaryHelpers(unittest.TestCase):
    """G fix: _load_zones_summary_from_model prefers model.json (non-null hint);
    falls back to des_inputs when model is absent."""

    # ------------------------------------------------------------------ helpers
    def _make_model_json(self, path, zones):
        """Write a minimal model.json with the given load_zones list."""
        import json as _json

        with open(path, "w") as f:
            _json.dump({"load_zones": zones}, f)

    def _make_des_inputs_gz(self, path, zones):
        """Write a minimal des_inputs.json.gz with the given load_zones list."""
        import json as _json
        import gzip as _gzip

        with _gzip.open(path, "wb") as f:
            f.write(_json.dumps({"load_zones": zones}).encode())

    # ------------------------------------------------------------------ model helper
    def test_model_helper_returns_detected_location_as_hint(self):
        """_load_zones_summary_from_model: hint is the detected_location dict."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            model_path = os.path.join(d, "model.json")
            self._make_model_json(
                model_path,
                [
                    {
                        "id": 1,
                        "name": "Load zone 1",
                        "detected_location": {"x": 100.0, "y": 200.0, "z": 300.0},
                    },
                    {"id": 2, "name": "Load zone 2"},  # no detected_location
                ],
            )
            result = jobs_module.load_zones_summary_from_model(model_path)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[0]["name"], "Load zone 1")
        self.assertIsNotNone(
            result[0]["hint"], "hint must be non-null when detected_location present"
        )
        self.assertEqual(result[0]["hint"]["x"], 100.0)
        self.assertEqual(result[0]["hint"]["y"], 200.0)
        self.assertIsNone(
            result[1]["hint"], "hint must be None when detected_location absent"
        )

    def test_model_helper_missing_file_returns_empty(self):
        """load_zones_summary_from_model: missing path yields []."""
        result = jobs_module.load_zones_summary_from_model("/nonexistent/model.json")
        self.assertEqual(result, [])

    def test_model_helper_corrupt_file_returns_empty(self):
        """load_zones_summary_from_model: corrupt JSON yields [] (best-effort)."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "model.json")
            with open(bad, "w") as f:
                f.write("not json{{")
            result = jobs_module.load_zones_summary_from_model(bad)
        self.assertEqual(result, [])

    # ------------------------------------------------------------------ chooser
    def test_chooser_prefers_model_over_des_inputs(self):
        """pick_load_zones_summary: model present → uses model (non-null hints)."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            model_path = os.path.join(d, "model.json")
            des_path = os.path.join(d, "des.json.gz")
            self._make_model_json(
                model_path,
                [
                    {
                        "id": 1,
                        "name": "LZ1",
                        "detected_location": {"x": 1.0, "y": 2.0, "z": 3.0},
                    }
                ],
            )
            self._make_des_inputs_gz(
                des_path,
                [
                    {"id": 1, "name": "LZ1"}  # no location
                ],
            )
            result = jobs_module.pick_load_zones_summary(model_path, des_path)

        self.assertEqual(len(result), 1)
        self.assertIsNotNone(
            result[0]["hint"], "chooser must prefer model (non-null hint)"
        )
        self.assertEqual(result[0]["hint"]["x"], 1.0)

    def test_chooser_falls_back_to_des_inputs_when_no_model(self):
        """pick_load_zones_summary: model absent → uses des_inputs (hint null)."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as d:
            des_path = os.path.join(d, "des.json.gz")
            self._make_des_inputs_gz(des_path, [{"id": 1, "name": "LZ1"}])
            result = jobs_module.pick_load_zones_summary(None, des_path)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)
        self.assertIsNone(result[0]["hint"])

    def test_chooser_no_artifacts_returns_empty(self):
        """pick_load_zones_summary: both absent → []."""
        result = jobs_module.pick_load_zones_summary(None, None)
        self.assertEqual(result, [])


class TestNotCompletedMessages(unittest.TestCase):
    """I-1: the not-completed message differs between export and import flows.

    Export → "Export not completed"
    Import → "Import/export not completed"
    """

    def setUp(self):
        jobs_module.export_status.clear()
        jobs_module.import_status.clear()

    def tearDown(self):
        jobs_module.export_status.clear()
        jobs_module.import_status.clear()

    def test_export_files_not_completed_returns_export_message(self):
        """GET /api/exports/{site}/files/model when status=processing → 400 'Export not completed'."""
        from litestar.testing import TestClient

        site = "TestExportSite"
        jobs_module.set_export_status(site, "processing", 0, "")

        with TestClient(app=app_module.app) as client:
            resp = client.get(f"/api/exports/{site}/files/model")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json().get("error"), "Export not completed")

    def test_import_files_not_completed_returns_import_message(self):
        """GET /api/imports/{name}/files/model when status=processing → 400 'Import/export not completed'."""
        from litestar.testing import TestClient

        name = "TestImportSite"
        jobs_module.set_import_status(name, "processing", 0, "")

        with TestClient(app=app_module.app) as client:
            resp = client.get(f"/api/imports/{name}/files/model")

        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json().get("error"), "Import/export not completed")


class TestImportLocation202(unittest.TestCase):
    """M4: POST /api/imports returning 202 must include Location: /api/imports/{sse_key}."""

    def test_import_202_includes_location_header(self):
        """A successful import POST (export=true) must return Location pointing to the SSE key."""
        from litestar.testing import TestClient
        import io as _io
        import zipfile as _zip

        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("f0.dat", b"x")
        buf.seek(0)

        captured = {}

        def fake_thread(target=None, args=(), **kwargs):
            captured["output_base_name"] = args[4]

            class _T:
                daemon = True

                def start(self):
                    pass

            return _T()

        with (
            mock.patch.object(
                imports_module, "parse_gateway_files", return_value={"ok": True}
            ),
            mock.patch.object(
                imports_module, "process_parser_output", return_value=[{"a": 1}]
            ),
            mock.patch.object(
                imports_module.threading, "Thread", side_effect=fake_thread
            ),
            mock.patch.object(imports_module.os.path, "exists", return_value=True),
        ):
            with TestClient(app=app_module.app) as client:
                resp = client.post(
                    "/api/imports",
                    data={"export": "true"},
                    files={"files": ("data.zip", buf, "application/zip")},
                )

        self.assertEqual(resp.status_code, 202, resp.text)
        # sse_key = output_base_name when not overridden, which falls back to
        # site_name ("DefaultSite") since no output_base_name was provided.
        site_name = "DefaultSite"
        expected_location = f"/api/imports/{site_name}"
        self.assertEqual(
            resp.headers.get("Location"),
            expected_location,
            f"202 response must include Location: {expected_location}",
        )


if __name__ == "__main__":
    unittest.main()
