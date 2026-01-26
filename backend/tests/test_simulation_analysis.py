"""
Regression tests for simulation_analysis audit findings.

Covers:
- H2: converter OBJECT branch must honor coordinates_in_meters (mm -> m).
- H8: RoadNavigator nearest-node uses NodeMatcher spatial grid (equivalent results).
- M7: calculate_segment_length guards coords[2] for 2-element coords.
- M11: sort key and event-time use identical field-resolution (interval vs actualElapsedTime).
- L9: circular-road traversal tracks current index (order, not just endpoint).
"""

import unittest
import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation_analysis.gps_to_events_converter import (
    GPSToEventsConverter,
)
from simulation_analysis.node_matcher import NodeMatcher
from simulation_analysis.road_navigator import RoadNavigator


class _FakeAMTMessage:
    """AMTCycleProdInfoMessage-like object exposing pathEasting etc."""

    def __init__(
        self,
        easting_mm,
        northing_mm,
        elevation_mm,
        segment_id=1000,
        elapsed_ms=0,
        speed=10.0,
        payload=0,
    ):
        self.pathEasting = easting_mm
        self.pathNorthing = northing_mm
        self.pathElevation = elevation_mm
        self.actualSpeed = speed
        self.payloadPercent = payload
        self.actualTime = None
        self.segmentId = segment_id
        self.actualElapsedTime = elapsed_ms


def _simple_model():
    """A minimal model with one straight road in metres."""
    nodes = [
        {"id": 1, "name": "N1", "coords": [0.0, 0.0, 0.0]},
        {"id": 2, "name": "N2", "coords": [100.0, 0.0, 0.0]},
        {"id": 3, "name": "N3", "coords": [200.0, 0.0, 0.0]},
    ]
    roads = [{"id": 1, "name": "R1", "nodes": [1, 2, 3]}]
    return {"nodes": nodes, "roads": roads}


class TestH2ObjectBranchUnits(unittest.TestCase):
    """H2: object branch must divide by 1000 when coordinates_in_meters=False."""

    def setUp(self):
        self.conv = GPSToEventsConverter(model_data=_simple_model())

    def test_object_branch_converts_mm_to_metres(self):
        # 100000 mm == 100 m. With the bug this stays 100000 (mm scale).
        self.conv._coordinates_in_meters = False
        msg = _FakeAMTMessage(100000, 0, 0)
        data = self.conv._extract_message_data(msg)
        self.assertAlmostEqual(data["x"], 100.0)
        self.assertAlmostEqual(data["y"], 0.0)
        self.assertAlmostEqual(data["z"], 0.0)

    def test_object_branch_metres_passthrough(self):
        self.conv._coordinates_in_meters = True
        msg = _FakeAMTMessage(100.0, 0.0, 0.0)
        data = self.conv._extract_message_data(msg)
        self.assertAlmostEqual(data["x"], 100.0)

    def test_object_branch_yields_events_with_mm_coords(self):
        # End-to-end: mm coords + coordinates_in_meters=False should match nodes
        # (metre-scale) and therefore produce events.
        messages = [
            _FakeAMTMessage(0, 0, 0, elapsed_ms=0),
            _FakeAMTMessage(100000, 0, 0, elapsed_ms=10000),
            _FakeAMTMessage(200000, 0, 0, elapsed_ms=20000),
        ]
        events = self.conv.convert_messages(
            messages,
            machine_id=1,
            machine_name="T1",
            coordinates_in_meters=False,
            min_node_distance=5.0,
            max_search_distance=50.0,
        )
        self.assertTrue(len(events) > 0)


class TestH8NearestNodeUsesGrid(unittest.TestCase):
    """H8: RoadNavigator nearest-node must equal NodeMatcher grid result."""

    def _random_model(self, n=200, seed=7):
        rng = random.Random(seed)
        nodes = []
        for i in range(1, n + 1):
            nodes.append(
                {
                    "id": i,
                    "name": f"N{i}",
                    "coords": [rng.uniform(0, 5000), rng.uniform(0, 5000), 0.0],
                }
            )
        # Chain them all into a single road
        roads = [{"id": 1, "name": "R", "nodes": [n["id"] for n in nodes]}]
        return nodes, roads

    @staticmethod
    def _brute_force_nearest(nodes, x, y, max_distance):
        """Ground-truth O(N) nearest-node scan."""
        import math

        best_id = None
        best_dist = float("inf")
        for n in nodes:
            c = n["coords"]
            d = math.sqrt((c[0] - x) ** 2 + (c[1] - y) ** 2)
            if d < best_dist and d <= max_distance:
                best_dist = d
                best_id = n["id"]
        if best_id is None:
            return None
        return (best_id, best_dist)

    def test_equivalence_with_brute_force(self):
        # The grid-backed lookup must return the SAME node/distance as a full scan.
        nodes, roads = self._random_model()
        nodes_dict = {n["id"]: n for n in nodes}
        max_dist = 300.0
        nav = RoadNavigator(nodes=nodes_dict, roads=roads, max_search_distance=max_dist)

        rng = random.Random(99)
        for _ in range(300):
            x = rng.uniform(-100, 5100)
            y = rng.uniform(-100, 5100)
            nav_res = nav._find_nearest_node_global(x, y, 0.0)
            truth = self._brute_force_nearest(nodes, x, y, max_dist)
            if truth is None:
                self.assertIsNone(nav_res)
            else:
                self.assertIsNotNone(nav_res)
                self.assertEqual(nav_res[0], truth[0])
                self.assertAlmostEqual(nav_res[1], truth[1], places=6)


class TestM7SegmentLengthGuard(unittest.TestCase):
    """M7: calculate_segment_length must not IndexError on 2-element coords."""

    def test_two_element_coords(self):
        nodes = [
            {"id": 1, "name": "N1", "coords": [0.0, 0.0]},
            {"id": 2, "name": "N2", "coords": [3.0, 4.0]},
        ]
        matcher = NodeMatcher(nodes, [])
        # Should be 5.0 (3-4-5 triangle), with z treated as 0.
        length = matcher.calculate_segment_length(1, 2)
        self.assertAlmostEqual(length, 5.0)

    def test_mixed_coord_lengths(self):
        nodes = [
            {"id": 1, "name": "N1", "coords": [0.0, 0.0, 10.0]},
            {"id": 2, "name": "N2", "coords": [0.0, 0.0]},  # 2-element
        ]
        matcher = NodeMatcher(nodes, [])
        # Missing z treated as 0, so vertical diff is 10.
        length = matcher.calculate_segment_length(1, 2)
        self.assertAlmostEqual(length, 10.0)


class TestM11SortVsEventTime(unittest.TestCase):
    """M11: _get_message_time and event-time must use identical resolution."""

    def setUp(self):
        self.conv = GPSToEventsConverter(model_data=_simple_model())

    def test_dict_with_interval_sorts_consistently(self):
        # Two dicts on same segment, carrying 'interval' but NOT actualElapsedTime.
        m_late = {
            "segment_id": 1000,
            "interval": 20000,
            "pathEasting": 0,
            "pathNorthing": 0,
            "pathElevation": 0,
            "actualSpeed": 5,
            "payloadPercent": 0,
        }
        m_early = {
            "segment_id": 1000,
            "interval": 5000,
            "pathEasting": 0,
            "pathNorthing": 0,
            "pathElevation": 0,
            "actualSpeed": 5,
            "payloadPercent": 0,
        }

        # Sort key must reflect interval ordering.
        t_late = self.conv._get_message_time(m_late)
        t_early = self.conv._get_message_time(m_early)
        self.assertLess(t_early, t_late)

        # And must match the event-time computation in _extract_message_data.
        self.conv._coordinates_in_meters = True
        d_late = self.conv._extract_message_data(m_late)
        d_early = self.conv._extract_message_data(m_early)
        self.assertEqual(t_late, d_late["time"])
        self.assertEqual(t_early, d_early["time"])


class TestL9CircularRoadOrder(unittest.TestCase):
    """L9: circular road must track current index, not first .index()."""

    def test_traversal_order_on_circular_road(self):
        nodes = {
            1: {"id": 1, "name": "N1", "coords": [0.0, 0.0, 0.0]},
            2: {"id": 2, "name": "N2", "coords": [100.0, 0.0, 0.0]},
            3: {"id": 3, "name": "N3", "coords": [100.0, 100.0, 0.0]},
        }
        # Circular: 1 -> 2 -> 3 -> 1 (node 1 appears twice).
        roads = [{"id": 1, "name": "Circle", "nodes": [1, 2, 3, 1]}]
        nav = RoadNavigator(nodes=nodes, roads=roads, max_search_distance=80.0)

        nav.navigate_to_gps(0.0, 0.0, 0.0)  # Node 1 (index 0)
        nav.navigate_to_gps(100.0, 0.0, 0.0)  # Node 2 (index 1)
        nav.navigate_to_gps(100.0, 100.0, 0.0)  # Node 3 (index 2)
        result = nav.navigate_to_gps(0.0, 0.0, 0.0)  # Back to Node 1 via index 3

        self.assertIsNotNone(result)
        self.assertEqual(result.node_id, 1)
        # Visited order must be a proper forward traversal ending at node 1,
        # i.e. the last entry is node 1 reached AFTER node 3 (no backward jump).
        visited = nav.get_visited_nodes()
        self.assertEqual(visited, [1, 2, 3, 1])
        # The navigator should land on the SECOND occurrence of node 1 (index 3),
        # not jump backward to index 0.
        self.assertEqual(nav.state.current_node_index, 3)


if __name__ == "__main__":
    unittest.main()
