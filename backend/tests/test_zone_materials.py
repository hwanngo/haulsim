import os
import sys
import unittest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))

from scripts.simgen.loaders import (  # noqa: E402
    build_material_catalog,
    build_material_properties,
    resolve_zone_material_assignment,
)
import tests.golden.generate_golden as gg  # noqa: E402

# A minimal in-memory materials.json stand-in (loose_density_tpm3 in t/m³).
MATERIALS = {
    "materials": [
        {"name": "copper_ore", "display_name": "Copper ore", "loose_density_tpm3": 1.6},
        {"name": "iron_ore", "display_name": "Iron ore", "loose_density_tpm3": 2.1},
        {"name": "coal", "display_name": "Coal", "loose_density_tpm3": 0.9},
    ]
}


class TestBuildMaterialCatalog(unittest.TestCase):
    def test_single_material_is_id_1_byte_identical_to_legacy(self):
        # The backward-compat linchpin: one material -> exactly the legacy shape.
        cat = build_material_catalog([("copper_ore", 1600.0)])
        self.assertEqual(
            cat,
            {"copper_ore_1600": {"id": 1, "material": "copper_ore", "density": 1600.0}},
        )
        self.assertEqual(cat, build_material_properties("copper_ore", 1600.0))

    def test_two_materials_ids_sorted_by_name(self):
        # coal < copper_ore alphabetically -> coal gets id 1.
        cat = build_material_catalog([("copper_ore", 1600.0), ("coal", 900.0)])
        self.assertEqual(cat["coal_900"]["id"], 1)
        self.assertEqual(cat["copper_ore_1600"]["id"], 2)

    def test_duplicate_material_collapses_to_one_entry(self):
        cat = build_material_catalog([("copper_ore", 1600.0), ("copper_ore", 1600.0)])
        self.assertEqual(len(cat), 1)
        self.assertEqual(cat["copper_ore_1600"]["id"], 1)


class TestResolveZoneMaterialAssignment(unittest.TestCase):
    def _zones(self):
        return [{"id": 1, "name": "Load zone 1"}, {"id": 2, "name": "Load zone 2"}]

    def test_no_map_all_zones_use_site_default(self):
        r = resolve_zone_material_assignment(
            self._zones(), None, "copper_ore", MATERIALS
        )
        self.assertEqual(
            r.catalog,
            {"copper_ore_1600": {"id": 1, "material": "copper_ore", "density": 1600.0}},
        )
        self.assertEqual(r.zone_id_to_key, {1: "copper_ore_1600", 2: "copper_ore_1600"})
        self.assertEqual(
            r.zone_name_to_md,
            {
                "Load zone 1": ("copper_ore", 1600.0),
                "Load zone 2": ("copper_ore", 1600.0),
            },
        )
        self.assertEqual(r.warnings, [])

    def test_per_zone_assignment_builds_multi_catalog(self):
        r = resolve_zone_material_assignment(
            self._zones(), {2: "iron_ore"}, "copper_ore", MATERIALS
        )
        self.assertEqual(r.zone_id_to_key, {1: "copper_ore_1600", 2: "iron_ore_2100"})
        self.assertEqual(r.zone_name_to_md["Load zone 2"], ("iron_ore", 2100.0))
        # catalog = exactly the distinct assigned materials, ids sorted by name
        self.assertEqual(set(r.catalog), {"copper_ore_1600", "iron_ore_2100"})
        self.assertEqual(r.catalog["copper_ore_1600"]["id"], 1)
        self.assertEqual(r.catalog["iron_ore_2100"]["id"], 2)

    def test_all_default_map_collapses_to_single_entry(self):
        # Map present but every value == site default -> identical to no-map path.
        r_map = resolve_zone_material_assignment(
            self._zones(), {1: "copper_ore", 2: "copper_ore"}, "copper_ore", MATERIALS
        )
        r_none = resolve_zone_material_assignment(
            self._zones(), None, "copper_ore", MATERIALS
        )
        self.assertEqual(r_map.catalog, r_none.catalog)
        self.assertEqual(r_map.zone_id_to_key, r_none.zone_id_to_key)
        self.assertEqual(len(r_map.catalog), 1)

    def test_unmatched_key_warns_and_falls_back_to_default(self):
        # Zone id 99 not detected -> warning, no effect on output, job proceeds.
        r = resolve_zone_material_assignment(
            self._zones(), {99: "iron_ore"}, "copper_ore", MATERIALS
        )
        self.assertEqual(set(r.catalog), {"copper_ore_1600"})
        self.assertEqual(r.zone_id_to_key, {1: "copper_ore_1600", 2: "copper_ore_1600"})
        self.assertTrue(any("99" in w for w in r.warnings))
        self.assertTrue(
            any("does not match any detected load zone" in w for w in r.warnings),
            "Warning must contain the phrase 'does not match any detected load zone'",
        )

    def test_catalog_is_exactly_distinct_assigned(self):
        # iron_ore assigned to both zones -> only iron_ore in catalog, no orphan default.
        r = resolve_zone_material_assignment(
            self._zones(), {1: "iron_ore", 2: "iron_ore"}, "copper_ore", MATERIALS
        )
        self.assertEqual(set(r.catalog), {"iron_ore_2100"})


class TestDesPerZoneRefs(unittest.TestCase):
    def test_create_des_inputs_uses_resolved_catalog_and_per_zone_refs(self):
        from scripts.simgen.des import create_des_inputs
        from scripts.simgen.loaders import resolve_zone_material_assignment

        model = {
            "nodes": [],
            "roads": [],
            "load_zones": [
                {"id": 1, "name": "Load zone 1"},
                {"id": 2, "name": "Load zone 2"},
            ],
            "dump_zones": [{"id": 1, "name": "Dump zone 1"}],
            "routes": [],
        }
        res = resolve_zone_material_assignment(
            model["load_zones"], {2: "iron_ore"}, "copper_ore", MATERIALS
        )
        des = create_des_inputs(
            model,
            {},
            "TestSite",
            sim_time=480,
            material="copper_ore",
            density=1600.0,
            material_catalog=res.catalog,
            zone_id_to_key=res.zone_id_to_key,
            zone_material_map=res.zone_name_to_md,
        )
        self.assertEqual(
            set(des["material_properties"]), {"copper_ore_1600", "iron_ore_2100"}
        )
        lz = {z["id"]: z for z in des["load_zones"]}
        self.assertEqual(lz[1]["material"], ["copper_ore_1600"])
        self.assertEqual(lz[2]["material"], ["iron_ore_2100"])


class TestSchedulePerZone(unittest.TestCase):
    def test_schedule_entry_carries_its_zone_material(self):
        from scripts.simgen.operations import create_material_schedule_from_trips

        trips_by_machine = {
            10: [{"load_zone_name": "Load zone 1", "dump_zone_name": "Dump zone 1"}],
            20: [{"load_zone_name": "Load zone 2", "dump_zone_name": "Dump zone 1"}],
        }
        zmap = {
            "Load zone 1": ("copper_ore", 1600.0),
            "Load zone 2": ("iron_ore", 2100.0),
        }
        data = create_material_schedule_from_trips(
            trips_by_machine,
            machine_id_to_hauler_group={10: 1, 20: 2},
            default_material="copper_ore",
            default_density=1600.0,
            zone_material_map=zmap,
        )
        by_lz = {d["load_zone"]: d for d in data}
        self.assertEqual(
            (by_lz["Load zone 1"]["material"], by_lz["Load zone 1"]["density"]),
            ("copper_ore", 1600.0),
        )
        self.assertEqual(
            (by_lz["Load zone 2"]["material"], by_lz["Load zone 2"]["density"]),
            ("iron_ore", 2100.0),
        )


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestProcessSitePerZone(unittest.TestCase):
    def test_two_zone_materials_produce_multi_catalog(self):
        import tempfile
        import tests.golden.generate_golden as gg

        # Discover the detected load-zone ids from a baseline (no-map) export first,
        # then assign a distinct material to the second zone and re-export.
        with tempfile.TemporaryDirectory() as d0:
            gg.export_to(d0)  # default single-material export
            base = gg.read_export(d0)
        lz_ids = sorted(z["id"] for z in base["des_inputs"]["load_zones"])
        if len(lz_ids) < 2:
            self.skipTest("baseline site has <2 load zones")

        with tempfile.TemporaryDirectory() as d1:
            gg.export_to(d1, zone_materials={lz_ids[1]: "iron_ore"})
            out = gg.read_export(d1)
        cat = out["des_inputs"]["material_properties"]
        self.assertIn("iron_ore_2100", cat)
        lz = {z["id"]: z for z in out["des_inputs"]["load_zones"]}
        self.assertEqual(lz[lz_ids[1]]["material"], ["iron_ore_2100"])


@unittest.skipUnless(gg.seed_available(), "DuckDB seed / site not available")
class TestMultiMaterialGolden(unittest.TestCase):
    def test_multi_material_matches_baseline(self):
        import tempfile
        import json
        import tests.golden.generate_golden as gg

        with tempfile.TemporaryDirectory() as d:
            gg.export_to(d, zone_materials=gg.MULTI_ZONE_MATERIALS)
            out = gg.read_export(d)
        with open(gg.MULTI_BASELINE_PATH) as f:
            baseline = json.load(f)
        self.assertEqual(
            json.dumps(out, sort_keys=True), json.dumps(baseline, sort_keys=True)
        )

    def test_multi_material_deterministic_3_runs(self):
        import tempfile
        import json
        import tests.golden.generate_golden as gg

        dumps = []
        for _ in range(3):
            with tempfile.TemporaryDirectory() as d:
                gg.export_to(d, zone_materials=gg.MULTI_ZONE_MATERIALS)
                dumps.append(json.dumps(gg.read_export(d), sort_keys=True))
        self.assertEqual(dumps[0], dumps[1])
        self.assertEqual(dumps[1], dumps[2])

    def test_all_default_map_is_byte_identical_to_no_map(self):
        import tempfile
        import json
        import tests.golden.generate_golden as gg

        with tempfile.TemporaryDirectory() as d0:
            gg.export_to(d0)
            none_dump = json.dumps(gg.read_export(d0), sort_keys=True)
        # Build an all-default map over the detected zones.
        base = json.loads(none_dump)
        all_default = {z["id"]: "copper_ore" for z in base["des_inputs"]["load_zones"]}
        with tempfile.TemporaryDirectory() as d1:
            gg.export_to(d1, zone_materials=all_default)
            map_dump = json.dumps(gg.read_export(d1), sort_keys=True)
        self.assertEqual(none_dump, map_dump)

    def test_single_material_catalog_is_id_1(self):
        import tempfile
        import tests.golden.generate_golden as gg

        with tempfile.TemporaryDirectory() as d:
            gg.export_to(d)
            out = gg.read_export(d)
        cat = out["des_inputs"]["material_properties"]
        self.assertEqual(len(cat), 1)
        self.assertEqual(next(iter(cat.values()))["id"], 1)


if __name__ == "__main__":
    unittest.main()
