"""
Task B-1: Tests for build_machine_id_to_hauler_group shared helper.

These tests verify that the helper reproduces the exact filter + ordering rule
from create_model's hauler-build loop (machines.items() order, events filter,
model-name/machine-list filter).
"""

import os
import sys
import unittest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
for p in (
    BACKEND_DIR,
    os.path.normpath(os.path.join(BACKEND_DIR, "..")),
    os.path.join(BACKEND_DIR, "scripts"),
):
    sys.path.insert(0, p)

import simulation_generator as sg  # noqa: E402


class TestHaulerGroupHelper(unittest.TestCase):
    def test_orders_and_filters(self):
        machines = {  # insertion order deliberately NOT sorted by id
            30: {"type_name": "CAT 793F CMD"},
            10: {"type_name": "CAT 793F CMD"},
            20: {"type_name": "CAT 793F CMD"},
        }
        mlist = {"793F": 1}  # all map to a known model
        m = sg.build_machine_id_to_hauler_group(
            machines,
            machines_with_events={10, 20, 30},
            model_name_to_machine_list_id=mlist,
        )
        # incrementing in machines.items() order (NOT sorted): 30->1, 10->2, 20->3
        self.assertEqual(m, {30: 1, 10: 2, 20: 3})

    def test_skips_filtered_machine(self):
        machines = {
            10: {"type_name": "CAT 793F CMD"},
            20: {"type_name": "CAT 793F CMD"},
        }
        mlist = {"793F": 1}
        m = sg.build_machine_id_to_hauler_group(
            machines, machines_with_events={10}, model_name_to_machine_list_id=mlist
        )
        self.assertEqual(m, {10: 1})  # 20 filtered out (no events), not assigned

    def test_no_events_filter_includes_all(self):
        """When machines_with_events=None, all machines with a known model are included."""
        machines = {5: {"type_name": "CAT 793F CMD"}, 3: {"type_name": "CAT 793F CMD"}}
        mlist = {"793F": 1}
        m = sg.build_machine_id_to_hauler_group(
            machines, machines_with_events=None, model_name_to_machine_list_id=mlist
        )
        self.assertEqual(m, {5: 1, 3: 2})

    def test_skips_machine_with_unknown_model(self):
        """A machine whose model_name is not in model_name_to_machine_list_id is skipped."""
        machines = {
            10: {"type_name": "CAT 793F CMD"},
            20: {"type_name": "UNKNOWN TRUCK X9"},
        }
        mlist = {"793F": 1}
        m = sg.build_machine_id_to_hauler_group(
            machines, machines_with_events={10, 20}, model_name_to_machine_list_id=mlist
        )
        # Machine 20 has an unrecognised type_name → extract_machine_model returns something
        # not in mlist → skipped; machine 10 gets group 1
        self.assertIn(10, m)
        self.assertNotIn(20, m)
        self.assertEqual(m[10], 1)

    def test_no_model_name_filter_includes_all_with_events(self):
        """When model_name_to_machine_list_id=None, only the events filter applies."""
        machines = {10: {"type_name": "CAT 793F CMD"}, 20: {"type_name": "OTHER MODEL"}}
        m = sg.build_machine_id_to_hauler_group(
            machines, machines_with_events={10, 20}, model_name_to_machine_list_id=None
        )
        self.assertEqual(m, {10: 1, 20: 2})

    def test_empty_machines(self):
        m = sg.build_machine_id_to_hauler_group(
            {}, machines_with_events=None, model_name_to_machine_list_id=None
        )
        self.assertEqual(m, {})


class TestBAcc1SemanticNumbering(unittest.TestCase):
    """
    B-acc-1: DES schedule hauler_group_id must use the same numbering basis as
    the DES hauler `id` loop — machines.items() insertion order with events-only
    filter (no model-name filter).

    Exercises two divergence axes via create_des_inputs (the real code path):
      (i) machines.items() order != sorted(machine_id) order
      (ii) a machine present in `machines` WITH events but producing no trips
           (shifts IDs of later machines in the DES hauler loop)

    Pre-fix: _create_des_operations is called WITHOUT machine_id_to_hauler_group,
    so create_material_schedule_from_trips falls back to sorted(trips_by_machine.keys())
    giving WRONG group numbering. This test FAILS pre-fix.
    Post-fix: create_des_inputs computes and passes mid_to_group matching DES hauler ids.
    """

    def _make_telemetry_for_machine(self, machine_id, lz_x, lz_y, dz_x, dz_y):
        """
        Create minimal telemetry tuples (matching analyze_hauler_trips_from_telemetry format)
        for one complete trip: empty → load → dump → empty.

        Tuple format: (machine_id[0], seg[1], cyc[2], ts[3], easting_m[4], northing_m[5],
                       elev_m[6], ...[7..12], payload_pct[13])
        """
        # Row 0: at load zone, empty (will become loaded)
        # Row 1: at load zone, loaded (triggers LOAD transition → records lz)
        # Row 2: at dump zone, empty (triggers DUMP transition → records dz & completes trip)
        pad = [0] * 7  # indices 6..12
        return [
            (machine_id, 1, 1, 1, lz_x, lz_y) + tuple(pad) + (30.0,),  # empty at lz
            (machine_id, 1, 1, 2, lz_x, lz_y)
            + tuple(pad)
            + (80.0,),  # loaded at lz → LOAD
            (machine_id, 1, 1, 3, dz_x, dz_y)
            + tuple(pad)
            + (10.0,),  # empty at dz → DUMP
        ]

    def _minimal_model(self, lz_x, lz_y, lz_name, dz_x, dz_y, dz_name):
        """Build the minimal model dict expected by create_des_inputs."""
        return {
            "nodes": [{"id": 1, "coords": [0, 0, 0]}],
            "roads": [],
            "load_zones": [
                {"id": 1, "name": lz_name, "detected_location": {"x": lz_x, "y": lz_y}}
            ],
            "dump_zones": [
                {"id": 1, "name": dz_name, "detected_location": {"x": dz_x, "y": dz_y}},
                {
                    "id": 2,
                    "name": dz_name + "2",
                    "detected_location": {"x": dz_x + 100, "y": dz_y},
                },
            ],
            "routes": [],
        }

    def test_hauler_group_id_axis_i_nonSorted_insertion_order(self):
        """
        Axis (i): machines.items() insertion order != sorted(machine_id) order.

        machines: {30: ..., 10: ..., 20: ...}   (insertion: 30, 10, 20)
        machines_with_events: {10, 20, 30}

        DES hauler-id loop (events-only, insertion order):
          30 -> hauler_id=1
          10 -> hauler_id=2
          20 -> hauler_id=3

        Trips: machine 30 → Dump_A (id=1), machine 10 → Dump_A2 (id=2).
        sorted fallback: sorted([10, 30]) = [10, 30] → {10:1, 30:2}
          → 30's trips get group 2 (WRONG; DES hauler for 30 has id=1)
          → 10's trips get group 1 (WRONG; DES hauler for 10 has id=2)

        Post-fix: group IDs match DES hauler ids.
        """
        machines = {
            30: {"type_name": "CAT 793F CMD", "name": "Hauler_30"},
            10: {"type_name": "CAT 793F CMD", "name": "Hauler_10"},
            20: {"type_name": "CAT 793F CMD", "name": "Hauler_20"},
        }
        machines_with_events = {10, 20, 30}

        # Machine 30 trips to Dump_A (id=1), machine 10 trips to Dump_A2 (id=2)
        # Zones at distinct positions; telemetry in meters (coordinates_in_meters=True)
        lz_x, lz_y = 0.0, 0.0
        dz_a_x, dz_a_y = 200.0, 0.0  # Dump_A → id=1
        dz_a2_x, dz_a2_y = 300.0, 0.0  # Dump_A2 → id=2

        model = {
            "nodes": [{"id": 1, "coords": [0, 0, 0]}],
            "roads": [],
            "load_zones": [
                {
                    "id": 1,
                    "name": "Pit1",
                    "detected_location": {"x": lz_x, "y": lz_y, "z": 0.0},
                }
            ],
            "dump_zones": [
                {
                    "id": 1,
                    "name": "Dump_A",
                    "detected_location": {"x": dz_a_x, "y": dz_a_y, "z": 0.0},
                },
                {
                    "id": 2,
                    "name": "Dump_A2",
                    "detected_location": {"x": dz_a2_x, "y": dz_a2_y, "z": 0.0},
                },
            ],
            "routes": [],
        }

        pad = [0] * 7
        telem_30 = [
            (30, 1, 1, 1, lz_x, lz_y) + tuple(pad) + (20.0,),
            (30, 1, 1, 2, lz_x, lz_y) + tuple(pad) + (80.0,),  # LOAD
            (30, 1, 1, 3, dz_a_x, dz_a_y) + tuple(pad) + (10.0,),  # DUMP → Dump_A
        ]
        telem_10 = [
            (10, 1, 1, 1, lz_x, lz_y) + tuple(pad) + (20.0,),
            (10, 1, 1, 2, lz_x, lz_y) + tuple(pad) + (80.0,),  # LOAD
            (10, 1, 1, 3, dz_a2_x, dz_a2_y) + tuple(pad) + (10.0,),  # DUMP → Dump_A2
        ]
        telemetry_data = telem_30 + telem_10

        des = sg.create_des_inputs(
            model=model,
            machines=machines,
            site_name="TestSite",
            machines_with_events=machines_with_events,
            telemetry_data=telemetry_data,
            coordinates_in_meters=True,
        )

        # Extract haulers: map hauler.name -> hauler.id (DES id)
        haulers = des.get("haulers", [])
        hauler_id_by_name = {h["name"]: h["id"] for h in haulers}
        # Haulers in insertion order: 30→id=1, 10→id=2, 20→id=3
        self.assertEqual(
            hauler_id_by_name.get("Hauler_30"),
            1,
            "Machine 30 must be DES hauler id=1 (insertion order)",
        )
        self.assertEqual(
            hauler_id_by_name.get("Hauler_10"),
            2,
            "Machine 10 must be DES hauler id=2 (insertion order)",
        )

        # Extract material schedule
        sched = des["operations"]["material_schedules"]["all_material_schedule"][0][
            "data"
        ]
        sched_by_dump = {item["dump_zone"]: item["hauler_group_id"] for item in sched}

        # Machine 30 (DES hauler id=1) → Dump_A → schedule must say group=1
        self.assertEqual(
            sched_by_dump.get("Dump_A"),
            1,
            "Dump_A trips from machine 30 must have hauler_group_id=1 (DES hauler id for 30)",
        )
        # Machine 10 (DES hauler id=2) → Dump_A2 → schedule must say group=2
        self.assertEqual(
            sched_by_dump.get("Dump_A2"),
            2,
            "Dump_A2 trips from machine 10 must have hauler_group_id=2 (DES hauler id for 10)",
        )

    def test_hauler_group_id_axis_ii_intermediate_machine_shifts_ids(self):
        """
        Axis (ii): machine 20 is in machines with events but produces no trips.
        Its presence in the DES hauler-id loop shifts machine 30's hauler id.

        machines: {10: ..., 20: ..., 30: ...}  (sorted insertion order)
        machines_with_events: {10, 20, 30}

        DES hauler-id loop:
          10 -> hauler_id=1
          20 -> hauler_id=2
          30 -> hauler_id=3

        Trips: machine 10 → Dump_A, machine 30 → Dump_B.
        sorted fallback: sorted([10, 30]) = [10, 30] → {10:1, 30:2}
          → 30's trips get group 2 (WRONG; DES hauler for 30 has id=3)

        Post-fix: 30's trips get group=3.
        """
        machines = {
            10: {"type_name": "CAT 793F CMD", "name": "Hauler_10"},
            20: {
                "type_name": "CAT 793F CMD",
                "name": "Hauler_20",
            },  # no trips; shifts 30's id
            30: {"type_name": "CAT 793F CMD", "name": "Hauler_30"},
        }
        machines_with_events = {10, 20, 30}

        lz_x, lz_y = 0.0, 0.0
        dz_a_x, dz_a_y = 200.0, 0.0
        dz_b_x, dz_b_y = 300.0, 0.0

        model = {
            "nodes": [{"id": 1, "coords": [0, 0, 0]}],
            "roads": [],
            "load_zones": [
                {
                    "id": 1,
                    "name": "Pit1",
                    "detected_location": {"x": lz_x, "y": lz_y, "z": 0.0},
                }
            ],
            "dump_zones": [
                {
                    "id": 1,
                    "name": "Dump_A",
                    "detected_location": {"x": dz_a_x, "y": dz_a_y, "z": 0.0},
                },
                {
                    "id": 2,
                    "name": "Dump_B",
                    "detected_location": {"x": dz_b_x, "y": dz_b_y, "z": 0.0},
                },
            ],
            "routes": [],
        }

        pad = [0] * 7
        telem_10 = [
            (10, 1, 1, 1, lz_x, lz_y) + tuple(pad) + (20.0,),
            (10, 1, 1, 2, lz_x, lz_y) + tuple(pad) + (80.0,),
            (10, 1, 1, 3, dz_a_x, dz_a_y) + tuple(pad) + (10.0,),
        ]
        telem_30 = [
            (30, 1, 1, 1, lz_x, lz_y) + tuple(pad) + (20.0,),
            (30, 1, 1, 2, lz_x, lz_y) + tuple(pad) + (80.0,),
            (30, 1, 1, 3, dz_b_x, dz_b_y) + tuple(pad) + (10.0,),
        ]
        telemetry_data = telem_10 + telem_30

        des = sg.create_des_inputs(
            model=model,
            machines=machines,
            site_name="TestSite",
            machines_with_events=machines_with_events,
            telemetry_data=telemetry_data,
            coordinates_in_meters=True,
        )

        haulers = des.get("haulers", [])
        hauler_id_by_name = {h["name"]: h["id"] for h in haulers}
        # Machine 20 is in machines_with_events → DES assigns it hauler id=2
        self.assertEqual(hauler_id_by_name.get("Hauler_10"), 1)
        self.assertEqual(hauler_id_by_name.get("Hauler_20"), 2)
        self.assertEqual(
            hauler_id_by_name.get("Hauler_30"),
            3,
            "Machine 30 DES hauler id must be 3 (20 is in events, takes id=2)",
        )

        sched = des["operations"]["material_schedules"]["all_material_schedule"][0][
            "data"
        ]
        sched_by_dump = {item["dump_zone"]: item["hauler_group_id"] for item in sched}

        # Machine 10 (DES hauler id=1) → Dump_A
        self.assertEqual(
            sched_by_dump.get("Dump_A"),
            1,
            "Dump_A trips from machine 10 must have hauler_group_id=1",
        )
        # Machine 30 (DES hauler id=3) → Dump_B; sorted fallback would say 2
        self.assertEqual(
            sched_by_dump.get("Dump_B"),
            3,
            "Dump_B trips from machine 30 must have hauler_group_id=3 (DES hauler id for 30)",
        )


# ---------------------------------------------------------------------------
# Task-3 fixtures: minimal 2×2 routable network
# ---------------------------------------------------------------------------
# Topology: LZ1 --road1--> hub(node3) --road2--> DZ1
#                                   \--road3--> DZ2
#           LZ2 --road4--> hub(node3)
# Return path: DZ1 --road5--> hub(node6) --road6--> LZ1
#              DZ2 --road7--> hub(node6) --road8--> LZ2
#
# All 4 load×dump pairs are routable via the shared hub nodes.
#
# Node layout:
#  1: LZ1 out-node  2: LZ2 out-node  3: haul hub
#  4: DZ1 in-node   5: DZ2 in-node
#  6: return hub    7: LZ1 in-node   8: LZ2 in-node
#  9: DZ1 out-node  10: DZ2 out-node

NODES2 = [{"id": i} for i in range(1, 11)]

ROADS2 = [
    {"id": 10, "nodes": [1, 3]},  # LZ1 out -> haul hub
    {"id": 11, "nodes": [2, 3]},  # LZ2 out -> haul hub
    {"id": 12, "nodes": [3, 4]},  # haul hub -> DZ1 in
    {"id": 13, "nodes": [3, 5]},  # haul hub -> DZ2 in
    {"id": 14, "nodes": [9, 6]},  # DZ1 out -> return hub
    {"id": 15, "nodes": [10, 6]},  # DZ2 out -> return hub
    {"id": 16, "nodes": [6, 7]},  # return hub -> LZ1 in
    {"id": 17, "nodes": [6, 8]},  # return hub -> LZ2 in
]

LZ2 = [
    {
        "id": 1,
        "name": "LoadZone1",
        "settings": {
            "outroad_ids": [10],
            "outnode_ids": [1],
            "inroad_ids": [16],
            "innode_ids": [7],
        },
    },
    {
        "id": 2,
        "name": "LoadZone2",
        "settings": {
            "outroad_ids": [11],
            "outnode_ids": [2],
            "inroad_ids": [17],
            "innode_ids": [8],
        },
    },
]

DZ2 = [
    {
        "id": 1,
        "name": "DumpZone1",
        "settings": {
            "inroad_ids": [12],
            "innode_ids": [4],
            "outroad_ids": [14],
            "outnode_ids": [9],
        },
    },
    {
        "id": 2,
        "name": "DumpZone2",
        "settings": {
            "inroad_ids": [13],
            "innode_ids": [5],
            "outroad_ids": [15],
            "outnode_ids": [10],
        },
    },
]


class TestObservedTripRouting(unittest.TestCase):
    def test_backward_compat_none_yields_geometric(self):
        """observed_pairs=None -> all 4 lz×dz pairs are generated."""
        routes = sg.create_routes(LZ2, DZ2, ROADS2, NODES2, observed_pairs=None)
        self.assertEqual(
            {(r["load_zone"], r["dump_zone"]) for r in routes},
            {(1, 1), (1, 2), (2, 1), (2, 2)},
        )

    def test_restricts_to_observed_pairs(self):
        """observed_pairs={(1,1),(2,2)} -> exactly those 2 routes emitted."""
        routes = sg.create_routes(
            LZ2, DZ2, ROADS2, NODES2, observed_pairs={(1, 1), (2, 2)}
        )
        self.assertEqual(
            {(r["load_zone"], r["dump_zone"]) for r in routes},
            {(1, 1), (2, 2)},
        )

    def test_multi_dump_from_one_load(self):
        """One load zone hauling to two dumps -> 2 distinct routes, both with haul."""
        routes = sg.create_routes(
            LZ2, DZ2, ROADS2, NODES2, observed_pairs={(1, 1), (1, 2)}
        )
        from_lz1 = [r for r in routes if r["load_zone"] == 1]
        self.assertEqual(len(from_lz1), 2)
        for r in from_lz1:
            self.assertTrue(r.get("haul"), f"Route {r} has empty haul path")


# ---------------------------------------------------------------------------
# Golden-based coherence and dangling-ref tests
# ---------------------------------------------------------------------------

try:
    import importlib.util as _ilu
    import os as _os

    _gg_path = _os.path.join(_os.path.dirname(__file__), "golden", "generate_golden.py")
    _spec = _ilu.spec_from_file_location("generate_golden", _gg_path)
    _gg = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_gg)
    _SEED_AVAIL = _gg.seed_available()
except Exception:
    _SEED_AVAIL = False
    _gg = None


@unittest.skipUnless(_SEED_AVAIL, "seed absent — skipping golden-based tests")
class TestRoutesMatchObservedHaulage(unittest.TestCase):
    """B's binding GREEN deliverable: emitted routes mirror observed haulage exactly.

    The set of (lz,dz) pairs in model['routes'] must EQUAL the set of observed
    (lz,dz) trip pairs from analyze_hauler_trips_from_telemetry — BOTH directions:
      - no fabrication: no route exists for a non-observed pair, and
      - no under-generation: every observed (routable) pair gets a route.
    This proves routes faithfully reflect what haulers actually did (B's charter).
    """

    def _observed_pairs_and_routes(self):
        import tempfile

        conn = sg.get_connection()
        cur = conn.cursor()
        machines = sg.fetch_machines(cur, _gg.SITE)
        tele = list(
            sg.fetch_telemetry_data(
                cur,
                machine_ids=list(machines.keys()),
                limit=_gg.CONFIG["limit"],
                sample_interval=_gg.CONFIG["sample_interval"],
            )
        )
        with tempfile.TemporaryDirectory() as d:
            _gg.export_to(d)
            m = _gg.read_export(d)["model"]
        trips = sg.analyze_hauler_trips_from_telemetry(
            tele, m["load_zones"], m["dump_zones"], False
        )
        observed = {
            (t["load_zone_name"], t["dump_zone_name"])
            for ts in trips.values()
            for t in ts
        }
        lz = {z["id"]: z.get("name") for z in m["load_zones"]}
        dz = {z["id"]: z.get("name") for z in m["dump_zones"]}
        route_pairs = {
            (lz.get(r["load_zone"]), dz.get(r["dump_zone"])) for r in m["routes"]
        }
        return observed, route_pairs

    def test_routes_equal_observed_pairs(self):
        observed, route_pairs = self._observed_pairs_and_routes()
        self.assertTrue(observed, "expected at least one observed haul pair")
        self.assertEqual(
            route_pairs,
            observed,
            f"Routes do not mirror observed haulage.\n"
            f"  Fabricated (routes not observed): {route_pairs - observed}\n"
            f"  Under-generated (observed without route): {observed - route_pairs}",
        )


@unittest.skipUnless(_SEED_AVAIL, "seed absent — skipping golden-based tests")
class TestDiscrepancySummary(unittest.TestCase):
    """Routing must log a discrepancy summary (no silent drop) — proxy-required."""

    def test_summary_logged(self):
        import io
        import contextlib
        import tempfile

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with tempfile.TemporaryDirectory() as d:
                _gg.export_to(d)
        out = buf.getvalue()
        self.assertIn("observed pairs", out)
        self.assertIn("routes emitted", out)
        self.assertIn("zero-trip zones", out)


@unittest.skipUnless(_SEED_AVAIL, "seed absent — skipping golden-based tests")
class TestRouteScheduleCoherence(unittest.TestCase):
    """Desired end-state: material-schedule (lz,dz) pairs == route (lz,dz) pairs.

    Marked expectedFailure: B made routes coherent with observed haulage, but the
    SCHEDULE side is broken by a PRE-EXISTING bug in
    create_material_schedule_from_trips (simgen/operations.py): each hauler is its
    own group with capacity 1, so the sorted (group_id, lz, dz) loop lets the first
    observed pair consume the capacity and silently drops every OTHER observed pair
    for that hauler (`remaining <= 0`). On BhpSpence this collapses 16 observed
    route pairs to 1 schedule pair.

    The correct fix is NOT a capacity tweak (emitting one entry per observed pair
    with num_of_hauler=1 would instantiate N trucks where 1 exists, inflating the
    simulated fleet). It needs the num_of_hauler modeling decision — per-route
    entries vs one group with multiple_routes=True spanning routes — which requires
    HaulSim ground truth. Routed to E (productivity accuracy / validation against
    real captures). When E fixes it, this test will pass unexpectedly → the suite
    goes red → the expectedFailure marker must be removed. That is the tripwire.
    """

    @unittest.expectedFailure
    def test_schedule_pairs_equal_route_pairs(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            _gg.export_to(d)
            m = _gg.read_export(d)["model"]
        lz_by_id = {z["id"]: z.get("name") for z in m["load_zones"]}
        dz_by_id = {z["id"]: z.get("name") for z in m["dump_zones"]}
        route_pairs = {
            (lz_by_id.get(r["load_zone"]), dz_by_id.get(r["dump_zone"]))
            for r in m["routes"]
        }
        sched = m["operations"]["material_schedules"]["all_material_schedule"][0][
            "data"
        ]
        sched_pairs = {(it["load_zone"], it["dump_zone"]) for it in sched}
        self.assertEqual(sched_pairs, route_pairs)


@unittest.skipUnless(_SEED_AVAIL, "seed absent — skipping golden-based tests")
class TestNoDanglingRouteRefs(unittest.TestCase):
    """Every route_id referenced in hauler initial_conditions must exist in model routes."""

    def _get_export(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            _gg.export_to(d)
            return _gg.read_export(d)

    def test_no_dangling_hauler_route_refs(self):
        docs = self._get_export()
        m = docs["model"]
        valid_route_ids = {r["id"] for r in m.get("routes", [])}

        haulers = docs["des_inputs"].get("haulers", [])
        checked = 0
        for hauler in haulers:
            ic = hauler.get("initial_conditions", {})
            route_id = ic.get("route_id")
            if route_id is not None:
                checked += 1
                self.assertIn(
                    route_id,
                    valid_route_ids,
                    f"Hauler {hauler.get('name')} references route_id={route_id} "
                    f"which is not in model routes {sorted(valid_route_ids)}",
                )
        self.assertGreater(
            checked, 0, "No haulers with route_id found — test would be vacuous"
        )


if __name__ == "__main__":
    unittest.main()


class TestE4ScheduleRoutability(unittest.TestCase):
    """E-4: the material schedule must not emit an entry for an observed (lz,dz)
    pair that has no emitted route (would dangle)."""

    def _trip(self, lz_name, dz_name):
        return {
            "load_zone_id": 1,
            "dump_zone_id": 1,
            "load_zone_name": lz_name,
            "dump_zone_name": dz_name,
        }

    def test_unroutable_observed_pair_omitted(self):
        # Machine 1 observed hauling LZ1->DZ1 (routable) and LZ1->DZ2 (NOT routable).
        trips_by_machine = {1: [self._trip("LZ1", "DZ1"), self._trip("LZ1", "DZ2")]}
        machine_id_to_hauler_group = {1: 1}
        load_zones = [{"id": 1, "name": "LZ1"}]
        dump_zones = [{"id": 1, "name": "DZ1"}, {"id": 2, "name": "DZ2"}]
        # Only LZ1->DZ1 has a route.
        routes = [{"load_zone": 1, "dump_zone": 1, "name": "LZ1 to DZ1"}]
        haulers = [{"group_id": 1, "number_of_haulers": 1}]

        items = sg.create_material_schedule_from_trips(
            trips_by_machine,
            routes=routes,
            haulers=haulers,
            machine_id_to_hauler_group=machine_id_to_hauler_group,
            load_zones=load_zones,
            dump_zones=dump_zones,
        )
        pairs = {(it["load_zone"], it["dump_zone"]) for it in items}
        self.assertIn(("LZ1", "DZ1"), pairs, "routable pair should be present")
        self.assertNotIn(
            ("LZ1", "DZ2"), pairs, "unroutable observed pair must be omitted (E-4)"
        )

    def test_routes_none_is_backward_compatible(self):
        # routes=None => no filtering (legacy behavior): both pairs emitted.
        trips_by_machine = {
            1: [self._trip("LZ1", "DZ1")],
            2: [self._trip("LZ1", "DZ2")],
        }
        machine_id_to_hauler_group = {1: 1, 2: 2}
        load_zones = [{"id": 1, "name": "LZ1"}]
        dump_zones = [{"id": 1, "name": "DZ1"}, {"id": 2, "name": "DZ2"}]
        haulers = [
            {"group_id": 1, "number_of_haulers": 1},
            {"group_id": 2, "number_of_haulers": 1},
        ]
        items = sg.create_material_schedule_from_trips(
            trips_by_machine,
            routes=None,
            haulers=haulers,
            machine_id_to_hauler_group=machine_id_to_hauler_group,
            load_zones=load_zones,
            dump_zones=dump_zones,
        )
        pairs = {(it["load_zone"], it["dump_zone"]) for it in items}
        self.assertEqual(pairs, {("LZ1", "DZ1"), ("LZ1", "DZ2")})
