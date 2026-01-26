"""
Durable job state backed by a writable DuckDB file.

Design decisions:
- Single module-level connection + threading.Lock (DuckDB is single-writer).
- Degrades to in-memory (no-op) on any DB failure — durability never breaks the job flow.
- Startup reconciliation: any 'processing' row surviving a prior crash is marked 'interrupted'.
"""

import json
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn = None  # module-level DuckDB connection; None when degraded


def init_job_store(path: str) -> None:
    """Open (or create) the DuckDB file and reconcile stale processing jobs."""
    global _conn
    try:
        import duckdb

        conn = duckdb.connect(path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_status (
                kind       TEXT,
                key        TEXT,
                status     TEXT,
                progress   INTEGER,
                message    TEXT,
                files_json TEXT,
                updated_at TIMESTAMP,
                PRIMARY KEY (kind, key)
            )
        """)
        # Startup reconciliation: threads that were running died on prior exit.
        conn.execute("""
            UPDATE job_status
            SET    status     = 'interrupted',
                   message    = 'Process restarted; job orphaned',
                   updated_at = CURRENT_TIMESTAMP
            WHERE  status = 'processing'
        """)
        conn.commit()
        _conn = conn
        logger.info("[job_store] Opened %s", path)
    except Exception as exc:
        logger.warning(
            "[job_store] Failed to open %s — degrading to in-memory: %s", path, exc
        )
        _conn = None


def persist(kind: str, key: str, data: dict) -> None:
    """Upsert a status record; silently degrades on any DB error."""
    if _conn is None:
        return
    files_json = json.dumps(data.get("files") or {})
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with _lock:
        try:
            _conn.execute(
                """
                INSERT INTO job_status (kind, key, status, progress, message, files_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (kind, key) DO UPDATE SET
                    status     = excluded.status,
                    progress   = excluded.progress,
                    message    = excluded.message,
                    files_json = excluded.files_json,
                    updated_at = excluded.updated_at
            """,
                [
                    kind,
                    key,
                    data.get("status", ""),
                    data.get("progress", 0),
                    data.get("message", ""),
                    files_json,
                    now,
                ],
            )
            _conn.commit()
        except Exception as exc:
            logger.warning("[job_store] persist failed (%s/%s): %s", kind, key, exc)


def load_all(kind: str) -> dict:
    """Return {key: {status, progress, message, files}} for the given kind."""
    if _conn is None:
        return {}
    with _lock:
        try:
            rows = _conn.execute(
                "SELECT key, status, progress, message, files_json FROM job_status WHERE kind = ?",
                [kind],
            ).fetchall()
        except Exception as exc:
            logger.warning("[job_store] load_all failed (kind=%s): %s", kind, exc)
            return {}
    result = {}
    for key, status, progress, message, files_json in rows:
        try:
            files = json.loads(files_json) if files_json else {}
        except Exception:
            files = {}
        result[key] = {
            "status": status,
            "progress": progress,
            "message": message,
            "files": files,
        }
    return result
