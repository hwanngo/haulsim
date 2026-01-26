"""Tests for durable job state (Task E1)."""

import os
import sys
import threading


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _fresh_store(path):
    """Load a clean job_store module state pointing at path."""
    # Evict any cached module so each test gets isolated global state
    for mod_name in list(sys.modules.keys()):
        if mod_name == "job_store":
            del sys.modules[mod_name]
    import job_store as js

    js._conn = None
    js.init_job_store(path)
    return js


class TestPersistAndLoad:
    def test_persisted_row_visible_to_fresh_store(self, tmp_path):
        db = str(tmp_path / "jobs.duckdb")
        js = _fresh_store(db)
        js.persist(
            "export",
            "site_a",
            {
                "status": "completed",
                "progress": 100,
                "message": "done",
                "files": {"model": "a.gz"},
            },
        )

        # Close this connection, open a fresh instance against same file
        js._conn.close()
        js2 = _fresh_store(db)
        result = js2.load_all("export")
        assert "site_a" in result
        assert result["site_a"]["status"] == "completed"
        assert result["site_a"]["files"]["model"] == "a.gz"

    def test_load_all_returns_empty_for_unknown_kind(self, tmp_path):
        db = str(tmp_path / "jobs.duckdb")
        js = _fresh_store(db)
        assert js.load_all("nonexistent") == {}


class TestStartupReconciliation:
    def test_processing_row_marked_interrupted_on_init(self, tmp_path):
        db = str(tmp_path / "jobs.duckdb")
        js = _fresh_store(db)
        js.persist(
            "export",
            "running_job",
            {"status": "processing", "progress": 50, "message": "...", "files": {}},
        )
        js._conn.close()

        # Simulate restart: second init_job_store call
        js2 = _fresh_store(db)
        result = js2.load_all("export")
        assert result["running_job"]["status"] == "interrupted"
        assert "orphaned" in result["running_job"]["message"]

    def test_completed_row_not_touched_on_init(self, tmp_path):
        db = str(tmp_path / "jobs.duckdb")
        js = _fresh_store(db)
        js.persist(
            "export",
            "done_job",
            {"status": "completed", "progress": 100, "message": "ok", "files": {}},
        )
        js._conn.close()

        js2 = _fresh_store(db)
        result = js2.load_all("export")
        assert result["done_job"]["status"] == "completed"


class TestConcurrency:
    def test_concurrent_persists_do_not_raise_or_corrupt(self, tmp_path):
        db = str(tmp_path / "jobs.duckdb")
        js = _fresh_store(db)

        barrier = threading.Barrier(2)
        errors = []

        def worker(site, status):
            try:
                barrier.wait()
                for i in range(10):
                    js.persist(
                        "export",
                        site,
                        {
                            "status": status,
                            "progress": i * 10,
                            "message": "",
                            "files": {},
                        },
                    )
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=("site_x", "processing"))
        t2 = threading.Thread(target=worker, args=("site_y", "completed"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Thread errors: {errors}"
        result = js.load_all("export")
        assert "site_x" in result
        assert "site_y" in result


class TestDegradation:
    def test_persist_to_bad_path_does_not_raise(self):
        for mod_name in list(sys.modules.keys()):
            if mod_name == "job_store":
                del sys.modules[mod_name]
        import job_store as js

        js._conn = None
        # Init with non-writable path — should degrade without raising
        js.init_job_store("/nonexistent_root/no/such/dir/jobs.duckdb")
        # persist must not raise even though _conn is None
        js.persist(
            "export",
            "any_site",
            {"status": "error", "progress": 0, "message": "fail", "files": {}},
        )
        assert js.load_all("export") == {}

    def test_load_all_on_none_conn_returns_empty(self):
        for mod_name in list(sys.modules.keys()):
            if mod_name == "job_store":
                del sys.modules[mod_name]
        import job_store as js

        js._conn = None
        assert js.load_all("import") == {}
