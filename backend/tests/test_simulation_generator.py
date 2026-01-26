"""
Tests for simulation_generator.py audit fixes.

Covers the behavioral findings:

  C2 - main() finally must not raise NameError when cursor creation fails
  H1 - explicit unit handling + magnitude safety warning in "meters" mode
  H7 - spatial-hash get_or_create_node merges points equivalently within tolerance
  M3 - a real 0 coordinate is kept (not treated as missing)
  M4 - load/dump zone classified by empty->loaded transition, not parked payload
  M6 - LIMIT is bound, not f-string interpolated
"""

import os
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))
sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))

import simulation_generator as sg  # noqa: E402


def make_row(
    machine_id, interval, x, y, z, actual_speed=0, payload=0, segment_id=1, cycle_id=1
):
    """Build a telemetry tuple in the canonical 14-field layout."""
    return (
        machine_id,  # 0 machine_id
        segment_id,  # 1 segment_id
        cycle_id,  # 2 cycle_id
        interval,  # 3 interval
        x,  # 4 pathEasting
        y,  # 5 pathNorthing
        z,  # 6 pathElevation
        0.0,  # 7 expectedSpeed
        actual_speed,  # 8 actualSpeed
        0.0,  # 9 pathBank
        0.0,  # 10 pathHeading
        0.0,  # 11 leftWidth
        0.0,  # 12 rightWidth
        payload,  # 13 payloadPercent
    )


class TestH7SpatialHashEquivalence(unittest.TestCase):
    """H7: spatial-hash node de-dup must merge the same points as the linear scan."""

    def _make_trajectory(self, machine_id, points):
        rows = []
        for i, (x, y, z) in enumerate(points):
            rows.append(make_row(machine_id, i * 5, x, y, z))
        return rows

    # A zig-zag path so Douglas-Peucker keeps every vertex (no collinear
    # midpoint removal) and the node count reflects de-dup behaviour only.
    ZIGZAG = [
        (0.0, 0.0, 0.0),
        (100.0, 80.0, 0.0),
        (200.0, 0.0, 0.0),
        (300.0, 80.0, 0.0),
    ]

    def test_distant_points_create_distinct_nodes(self):
        traj = self._make_trajectory(1, self.ZIGZAG)
        nodes, roads = sg.create_roads_from_trajectories(
            traj,
            simplify_epsilon=1.0,
            min_segment_distance=1.0,
            coordinates_in_meters=True,
        )
        # All four vertices are far apart -> four nodes.
        self.assertEqual(len(nodes), 4)

    def test_near_duplicate_points_merge(self):
        # A second machine retraces the first path, each vertex offset <5m.
        traj = self._make_trajectory(1, self.ZIGZAG)
        offset = [(x + 0.5, y + 0.5, z) for (x, y, z) in self.ZIGZAG]
        traj += self._make_trajectory(2, offset)
        nodes, roads = sg.create_roads_from_trajectories(
            traj,
            simplify_epsilon=1.0,
            min_segment_distance=1.0,
            coordinates_in_meters=True,
        )
        # The retraced vertices snap to the first path's nodes -> 4 unique.
        self.assertEqual(len(nodes), 4)

    def test_grid_boundary_match(self):
        # Two near-identical points straddling a grid-cell boundary (cell size
        # == tolerance == 5m) must still merge via the 9-neighbour scan.
        traj = self._make_trajectory(
            1,
            [
                (4.9, 4.9, 0.0),
                (100.0, 80.0, 0.0),
                (200.0, 4.9, 0.0),
            ],
        )
        traj += self._make_trajectory(
            2,
            [
                (5.1, 5.1, 0.0),  # 0.28m from (4.9,4.9) but different cell
                (100.0, 80.0, 0.0),
                (200.0, 5.1, 0.0),
            ],
        )
        nodes, roads = sg.create_roads_from_trajectories(
            traj,
            simplify_epsilon=1.0,
            min_segment_distance=1.0,
            coordinates_in_meters=True,
        )
        # (4.9,4.9) and (5.1,5.1) must collapse to one node despite the boundary.
        near_origin = [
            n for n in nodes if abs(n["coords"][0]) < 10 and abs(n["coords"][1]) < 10
        ]
        self.assertEqual(
            len(near_origin),
            1,
            f"boundary points did not merge: {[n['coords'] for n in nodes]}",
        )


class TestM3ZeroCoordinateKept(unittest.TestCase):
    """M3: a real coordinate of 0 must not be dropped to "missing"."""

    def test_zero_coordinate_preserved_meters(self):
        # Stopped points clustered at x=0 (a legitimate coordinate).
        rows = []
        for i in range(30):
            rows.append(make_row(1, i, 0.0, 25.0, 0.0, actual_speed=0, payload=10))
        # Provide a road whose endpoint is at (0,25) so the zone is accepted.
        nodes = [
            {"id": 1, "coords": [0.0, 25.0, 0.0]},
            {"id": 2, "coords": [200.0, 25.0, 0.0]},
        ]
        roads = [{"id": 1, "nodes": [1, 2]}]
        load_zones, dump_zones = sg.detect_zones(
            rows,
            nodes,
            roads,
            grid_size=10.0,
            min_stop_count=20,
            coordinates_in_meters=True,
        )
        all_zones = load_zones + dump_zones
        self.assertTrue(all_zones, "zone at x=0 was dropped (0 treated as missing)")
        loc = all_zones[0]["detected_location"]
        # The detected x must be 0 (the real coordinate), not shifted away.
        self.assertEqual(loc["x"], 0.0)


class TestM4ZoneClassification(unittest.TestCase):
    """M4: classify by empty->loaded transition, not mean parked payload."""

    def test_load_zone_with_high_parked_payload(self):
        # Build a load zone: trucks arrive empty, load up, and PARK loaded
        # (so the mean payload at the stop is high -> old code would mislabel
        # it as a dump zone).
        load_x, load_y = 0.0, 0.0
        dump_x, dump_y = 400.0, 0.0
        nodes = [
            {"id": 1, "coords": [load_x, load_y, 0.0]},
            {"id": 2, "coords": [dump_x, dump_y, 0.0]},
        ]
        roads = [{"id": 1, "nodes": [1, 2]}]

        rows = []
        t = 0
        # Several machines repeat the empty->loaded transition at the load zone.
        for m in range(3):
            # Approach empty, then sit loaded for a while (high parked payload).
            # empty arrival
            for _ in range(8):
                rows.append(
                    make_row(10 + m, t, load_x, load_y, 0.0, actual_speed=0, payload=0)
                )
                t += 1
            # loaded and parked (payload ~100) -> drives mean up
            for _ in range(15):
                rows.append(
                    make_row(
                        10 + m, t, load_x, load_y, 0.0, actual_speed=0, payload=100
                    )
                )
                t += 1
            # then dump zone: arrive loaded, become empty
            for _ in range(8):
                rows.append(
                    make_row(
                        10 + m, t, dump_x, dump_y, 0.0, actual_speed=0, payload=100
                    )
                )
                t += 1
            for _ in range(15):
                rows.append(
                    make_row(10 + m, t, dump_x, dump_y, 0.0, actual_speed=0, payload=0)
                )
                t += 1

        load_zones, dump_zones = sg.detect_zones(
            rows,
            nodes,
            roads,
            grid_size=10.0,
            min_stop_count=10,
            coordinates_in_meters=True,
        )

        def near(zlist, x, y):
            for z in zlist:
                loc = z["detected_location"]
                if abs(loc["x"] - x) < 20 and abs(loc["y"] - y) < 20:
                    return True
            return False

        # The cell at the loading location must be a LOAD zone despite the
        # high mean parked payload there.
        self.assertTrue(
            near(load_zones, load_x, load_y),
            f"load location misclassified; "
            f"load={[z['detected_location'] for z in load_zones]} "
            f"dump={[z['detected_location'] for z in dump_zones]}",
        )
        self.assertFalse(
            near(dump_zones, load_x, load_y),
            "load location was labelled a dump zone (M4 regression)",
        )


class TestM6LimitBound(unittest.TestCase):
    """M6: LIMIT must be parameterized, not f-string interpolated."""

    def test_meta_query_uses_bound_limit(self):
        captured = {}

        class FakeCursor:
            def execute(self, query, params=None):
                # The first execute is the metadata query.
                if (
                    "cycleProdInfoHandle" in query
                    and "ORDER BY" in query
                    and "amt_cycleprodinfo\n" in query
                    or "FROM amt_cycleprodinfo" in query
                ):
                    captured.setdefault("meta_query", query)
                    captured.setdefault("meta_params", params)
                captured.setdefault("all", []).append((query, params))

            def fetchall(self):
                return []

        sg.fetch_telemetry_data(FakeCursor(), machine_ids=[1, 2], limit=100000)
        meta_q = captured["all"][0][0]
        meta_p = captured["all"][0][1]
        # No literal computed LIMIT value should appear in the SQL text.
        self.assertNotIn("LIMIT 10000", meta_q)
        self.assertIn("LIMIT %s", meta_q)
        # The bound params must include the limit value.
        self.assertIn(100000 // 10, list(meta_p))


class TestH1UnitMagnitudeWarning(unittest.TestCase):
    """H1: warn when coordinates exceed a sane magnitude in 'meters' mode."""

    def test_warns_on_millimetre_magnitude_in_meters_mode(self):
        # > 1e7 "metres" = absurd; really mm data (~50 km) mislabelled as metres.
        big = 50_000_000.0
        rows = [
            make_row(1, 0, big, big, 100.0),
            make_row(1, 5, big + 100, big, 100.0),
        ]
        with mock.patch.object(sg, "_warn_coordinate_magnitude") as warn:
            sg.create_roads_from_trajectories(
                rows,
                simplify_epsilon=1.0,
                min_segment_distance=1.0,
                coordinates_in_meters=True,
            )
            self.assertTrue(
                warn.called, "no magnitude safety warning for absurd metre coords"
            )

    def test_no_warning_for_normal_metre_coords(self):
        rows = [
            make_row(1, 0, 100.0, 200.0, 10.0),
            make_row(1, 5, 150.0, 200.0, 10.0),
        ]
        with mock.patch.object(sg, "_warn_coordinate_magnitude") as warn:
            sg.create_roads_from_trajectories(
                rows,
                simplify_epsilon=1.0,
                min_segment_distance=1.0,
                coordinates_in_meters=True,
            )
            self.assertFalse(warn.called)


class TestC2MainFinallyGuards(unittest.TestCase):
    """C2: main() finally must guard cursor/connection (no NameError mask)."""

    def test_finally_does_not_raise_when_cursor_fails(self):
        # Connection whose .cursor() raises a DB error -> main() must handle it
        # and run finally WITHOUT raising NameError (the C2 bug), and must close
        # the connection.
        import duckdb

        class BadConn:
            closed = False

            def cursor(self):
                raise duckdb.Error("cursor boom")

            def close(self):
                self.closed = True

        bad = BadConn()
        argv = ["simulation_generator.py", "--site", "X"]
        with (
            mock.patch.object(sg, "get_connection", return_value=bad),
            mock.patch.object(sys, "argv", argv),
        ):
            try:
                sg.main()
            except NameError as e:  # pragma: no cover - this is the bug we fix
                self.fail(f"main() finally raised NameError: {e}")
            except SystemExit:
                pass
        self.assertTrue(bad.closed, "connection was not closed in finally")


if __name__ == "__main__":
    unittest.main()
