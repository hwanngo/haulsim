"""
Database connectivity and telemetry fetching — extracted from simulation_generator.py (behavior-preserving).
"""

import duckdb
from typing import Dict, List, Optional, Tuple

from backend.core.db_config import DUCKDB_PATH
from backend.scripts.simgen.constants import *  # noqa: F401, F403

try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    def tqdm(iterable, desc=None, total=None, disable=False, unit=None):
        return iterable


__all__ = [
    "_DuckCursor",
    "_DuckConnection",
    "get_connection",
    "fetch_sites",
    "fetch_machines",
    "fetch_telemetry_data",
]


class _DuckCursor:
    """DBAPI-ish cursor over DuckDB that translates the legacy MySQL SQL on the
    fly: backtick identifiers -> double quotes, %s placeholders -> ?. Lets the
    existing query strings run unchanged."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql, params=None):
        sql = sql.replace("`", '"').replace("%s", "?")
        self._con.execute(sql, list(params)) if params else self._con.execute(sql)
        return self

    def fetchall(self):
        return self._con.fetchall()

    def close(self):
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _DuckConnection:
    """Thin connection wrapper exposing the cursor()/close() surface the app
    expects (with-statement friendly)."""

    def __init__(self, path):
        self._con = duckdb.connect(path, read_only=True)

    def cursor(self):
        return _DuckCursor(self._con.cursor())

    def close(self):
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def get_connection():
    """Open the embedded DuckDB database (read-only). Returns None if missing."""
    try:
        return _DuckConnection(DUCKDB_PATH)
    except Exception as e:
        print(f"Error opening DuckDB database at {DUCKDB_PATH}: {e}")
        return None


def fetch_sites(cursor) -> List[Dict]:
    """Fetch list of available sites."""
    query = """
        SELECT DISTINCT m.`Site Name`, s.`SiteNameShort`, s.`SiteId`
        FROM amt_cycleprodinfo cp
        INNER JOIN machines m ON cp.`Machine Unique Id` = m.`Machine Unique Id`
        INNER JOIN site s ON m.`Site Name` = s.`Site Name`
        ORDER BY m.`Site Name`
    """
    cursor.execute(query)
    sites = []
    for row in cursor.fetchall():
        sites.append(
            {
                "site_name": row[0],
                "site_short": row[1],
                "site_id": row[2],
            }
        )
    return sites


def fetch_machines(cursor, site_name: Optional[str] = None) -> Dict[int, Dict]:
    """Fetch machine information."""
    query = """
        SELECT DISTINCT m.`Machine Unique Id`, m.`Machine Id`, m.`Name`,
               m.`TypeName`, m.`Autonomous`, m.`Site Name`
        FROM machines m
        INNER JOIN amt_cycleprodinfo cp ON m.`Machine Unique Id` = cp.`Machine Unique Id`
    """
    params = []
    if site_name:
        query += " WHERE m.`Site Name` = %s"
        params.append(site_name)

    # Deterministic row order: SELECT DISTINCT + JOIN has no inherent ordering, so
    # without this the machines dict order (and thus downstream hauler id/group_id
    # assignment) varies run-to-run. Order by the stable unique id.
    query += " ORDER BY m.`Machine Unique Id`"

    cursor.execute(query, params)
    machines = {}
    for row in cursor.fetchall():
        machines[row[0]] = {
            "machine_unique_id": row[0],
            "machine_id": row[1],
            "name": row[2],
            "type_name": row[3],
            "autonomous": row[4],
            "site_name": row[5],
        }
    return machines


def fetch_telemetry_data(
    cursor,
    machine_ids: List[int],
    limit: int = 100000,
    sample_interval: int = 5,
) -> List[Tuple]:
    """
    Fetch telemetry data from database.

    Returns list of tuples:
    (machine_id, segment_id, cycle_id, interval, pathEasting, pathNorthing,
     pathElevation, expectedSpeed, actualSpeed, pathBank, pathHeading,
     leftWidth, rightWidth, payloadPercent)
    """
    print("    Fetching segment metadata...")

    placeholders = ",".join(["%s"] * len(machine_ids))
    # NOTE: the metadata (segment) query is intentionally capped at limit // 10
    # segments. Each segment expands into many telemetry points downstream, so
    # this keeps the segment count ~10x below the point limit. Behavior is
    # preserved from the original implementation; only the binding changed from
    # an f-string to a parameter (M6).
    meta_limit = limit // 10
    meta_query = f"""
        SELECT `Machine Unique Id`, segmentId, cycleId, cycleProdInfoHandle
        FROM amt_cycleprodinfo
        WHERE `Machine Unique Id` IN ({placeholders})
        ORDER BY `Machine Unique Id`, segmentId
        LIMIT %s
    """

    cursor.execute(meta_query, list(machine_ids) + [meta_limit])
    metadata = cursor.fetchall()

    if not metadata:
        return []

    print(f"    Found {len(metadata)} segments")

    handle_to_meta = {}
    handles = []
    for row in metadata:
        handle = row[3]
        handles.append(handle)
        handle_to_meta[handle] = {
            "machine_id": row[0],
            "segment_id": row[1],
            "cycle_id": row[2],
        }

    print("    Fetching telemetry points...")

    results = []
    batch_size = 100

    batch_iterator = range(0, len(handles), batch_size)
    if TQDM_AVAILABLE:
        batch_iterator = tqdm(
            batch_iterator,
            desc="      Batches",
            total=(len(handles) + batch_size - 1) // batch_size,
            unit="batch",
        )

    for i in batch_iterator:
        batch_handles = handles[i : i + batch_size]
        placeholders = ",".join(["%s"] * len(batch_handles))

        telem_query = f"""
            SELECT
                cycleProdInfoHandle,
                `interval`,
                pathEasting,
                pathNorthing,
                pathElevation,
                expectedSpeed,
                actualSpeed,
                pathBank,
                pathHeading,
                leftWidth,
                rightWidth,
                payloadPercent
            FROM amt_cycleprodinfo_handle
            WHERE cycleProdInfoHandle IN ({placeholders})
                AND pathEasting IS NOT NULL
                AND pathNorthing IS NOT NULL
                AND pathElevation IS NOT NULL
                AND MOD(`interval`, %s) = 0
            ORDER BY cycleProdInfoHandle, `interval`
        """

        batch_params = batch_handles + [sample_interval]
        cursor.execute(telem_query, batch_params)
        batch_results = cursor.fetchall()

        for row in batch_results:
            handle = row[0]
            if handle in handle_to_meta:
                meta = handle_to_meta[handle]
                combined = (
                    meta["machine_id"],
                    meta["segment_id"],
                    meta["cycle_id"],
                    row[1],  # interval
                    row[2],  # pathEasting
                    row[3],  # pathNorthing
                    row[4],  # pathElevation
                    row[5],  # expectedSpeed
                    row[6],  # actualSpeed
                    row[7],  # pathBank
                    row[8],  # pathHeading
                    row[9],  # leftWidth
                    row[10],  # rightWidth
                    row[11],  # payloadPercent
                )
                results.append(combined)

        if len(results) >= limit:
            break

    # Sort by machine_id, cycle_id, segment_id, interval to ensure correct time order
    results.sort(key=lambda x: (x[0], x[2], x[1], x[3]))
    return results[:limit]
