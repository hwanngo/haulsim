"""Tests for reference-data (materials.json) activation in simulation_generator."""

import os
import sys
import unittest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))
sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))

import simulation_generator as sg  # noqa: E402


class TestMaterialsLoader(unittest.TestCase):
    def test_load_materials_returns_five_materials(self):
        materials = sg.load_materials()
        names = {m["name"] for m in materials.get("materials", [])}
        self.assertEqual(
            names,
            {"copper_ore", "iron_ore", "gold_ore", "coal", "overburden"},
        )

    def test_load_materials_missing_file_returns_empty(self):
        result = sg.load_materials("/nonexistent/materials.json")
        self.assertEqual(result, {})


class TestDensityResolution(unittest.TestCase):
    def test_default_material_is_copper_ore(self):
        self.assertEqual(sg.DEFAULT_MATERIAL, "copper_ore")

    def test_copper_ore_loose_density_kg_m3(self):
        # 1.6 t/m3 * 1000 = 1600.0 kg/m3 (NOT 1.6, NOT t/m3)
        self.assertEqual(sg.resolve_material_density("copper_ore"), 1600.0)

    def test_iron_ore_override_density(self):
        self.assertEqual(sg.resolve_material_density("iron_ore"), 2100.0)

    def test_case_insensitive_lookup(self):
        self.assertEqual(sg.resolve_material_density("COPPER_ORE"), 1600.0)

    def test_unknown_material_falls_back_to_default_constant(self):
        self.assertEqual(
            sg.resolve_material_density("unobtainium"),
            sg.DEFAULT_MATERIAL_DENSITY,
        )

    def test_missing_loose_density_field_falls_back(self):
        materials = {"materials": [{"name": "weird"}]}  # no loose_density_tpm3
        self.assertEqual(
            sg.resolve_material_density("weird", materials),
            sg.DEFAULT_MATERIAL_DENSITY,
        )


class TestMaterialValidation(unittest.TestCase):
    def test_known_material_returns_canonical_name(self):
        materials = sg.load_materials()
        self.assertEqual(
            sg.validate_material_name("copper_ore", materials), "copper_ore"
        )

    def test_unknown_material_raises_with_valid_list(self):
        materials = sg.load_materials()
        with self.assertRaises(ValueError) as ctx:
            sg.validate_material_name("unobtainium", materials)
        self.assertIn("copper_ore", str(ctx.exception))


class TestCatalogHelpers(unittest.TestCase):
    def test_catalog_key_embeds_int_density(self):
        self.assertEqual(
            sg.material_catalog_key("copper_ore", 1600.0), "copper_ore_1600"
        )

    def test_build_material_properties_single_entry(self):
        catalog = sg.build_material_properties("copper_ore", 1600.0)
        self.assertEqual(list(catalog.keys()), ["copper_ore_1600"])
        entry = catalog["copper_ore_1600"]
        self.assertEqual(entry["material"], "copper_ore")
        self.assertEqual(entry["density"], 1600.0)
        self.assertEqual(entry["id"], 1)


class TestDesInputsCoherence(unittest.TestCase):
    """Referential integrity across material_properties, zone refs, schedule items."""

    def _minimal_model(self):
        return {
            "nodes": [],
            "roads": [],
            "load_zones": [{"id": 1, "name": "LZ1"}],
            "dump_zones": [{"id": 1, "name": "DZ1"}],
        }

    def test_catalog_single_entry_for_chosen_material(self):
        des = sg.create_des_inputs(
            self._minimal_model(),
            machines={},
            site_name="S",
            material="copper_ore",
            density=1600.0,
        )
        catalog = des["material_properties"]
        # Order-independent assertions (dict ordering is implementation detail)
        self.assertEqual(len(catalog), 1)
        self.assertIn("copper_ore_1600", catalog)
        self.assertNotIn("Waste_1800", catalog)

    def test_load_zone_refs_resolve_to_catalog_key(self):
        des = sg.create_des_inputs(
            self._minimal_model(),
            machines={},
            site_name="S",
            material="copper_ore",
            density=1600.0,
        )
        catalog_keys = set(des["material_properties"].keys())
        # locate load zones wherever they live in des_inputs and assert refs valid
        refs = _collect_zone_material_refs(des)
        self.assertTrue(refs, "expected at least one load-zone material ref")
        for ref in refs:
            self.assertIn(ref, catalog_keys)

    def test_schedule_item_material_coherence(self):
        """Every emitted schedule item's material string and density must
        match the catalog entry for the chosen material.

        Path: des["operations"]["material_schedules"]["all_material_schedule"][0]["data"]
        Items are dicts with string-typed "material" (not a list like load-zone refs)
        plus "num_of_hauler" / "hauler_group_id" keys (distinguishes them from catalog
        entries which have an "id" key and no "num_of_hauler").
        """
        des = sg.create_des_inputs(
            self._minimal_model(),
            machines={},
            site_name="S",
            material="copper_ore",
            density=1600.0,
        )
        catalog = des["material_properties"]
        catalog_entry = catalog["copper_ore_1600"]

        items = _collect_schedule_items(des)
        # Sanity: minimal model (1 LZ + 1 DZ) must produce at least one schedule item
        self.assertTrue(items, "expected at least one material schedule item; got none")

        for item in items:
            # material string must be the internal name, not a display name
            self.assertEqual(
                item["material"],
                "copper_ore",
                f"schedule item material should be 'copper_ore', got {item['material']!r}",
            )
            # density must equal the explicit argument
            self.assertEqual(
                item["density"],
                1600.0,
                f"schedule item density should be 1600.0, got {item['density']}",
            )
            # density must be consistent with the catalog entry
            self.assertEqual(
                item["density"],
                catalog_entry["density"],
                "schedule item density must match catalog entry density",
            )

    def _model_with_detected_locations(self):
        """Model whose zones have detected_location so telemetry trip analysis fires."""
        return {
            "nodes": [],
            "roads": [],
            "load_zones": [
                {
                    "id": 1,
                    "name": "LZ1",
                    "detected_location": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
            ],
            "dump_zones": [
                {
                    "id": 1,
                    "name": "DZ1",
                    "detected_location": {"x": 400.0, "y": 0.0, "z": 0.0},
                },
            ],
        }

    def _telemetry_with_one_trip(self):
        """14-field telemetry tuples (meters) that complete one load→dump trip.

        Tuple layout: (machine_id, segment_id, cycle_id, interval,
                       x, y, z, expectedSpeed, actualSpeed, pathBank,
                       pathHeading, leftWidth, rightWidth, payloadPercent)
        Payload transitions:
          t=0  payload=0  near (0,0)   — empty at load zone
          t=1  payload=80 near (0,0)   — loaded (empty→loaded transition at load zone)
          t=2  payload=80 near (400,0) — still loaded, now at dump zone
          t=3  payload=0  near (400,0) — emptied (loaded→empty transition at dump zone)
        """

        def row(t, x, y, payload):
            return (1, 1, 1, t, x, y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, payload)

        return [
            row(0, 0.0, 0.0, 0),
            row(1, 0.0, 0.0, 80),
            row(2, 400.0, 0.0, 80),
            row(3, 400.0, 0.0, 0),
        ]

    def test_telemetry_trips_branch_forwards_material_and_density(self):
        """I1: when telemetry yields trips, schedule items must carry the chosen
        material/density — not the function defaults ("Ore" / 1960.19).

        This test exercises the TRIPS branch of _create_des_operations.
        It FAILS before the C1 fix (material=="Ore") and PASSES after.
        """
        des = sg.create_des_inputs(
            self._model_with_detected_locations(),
            machines={},
            site_name="S",
            telemetry_data=self._telemetry_with_one_trip(),
            coordinates_in_meters=True,
            material="copper_ore",
            density=1600.0,
        )

        catalog = des["material_properties"]
        catalog_entry = catalog["copper_ore_1600"]

        items = _collect_schedule_items(des)
        self.assertTrue(
            items,
            "telemetry trips branch produced no schedule items — trips branch may not have fired",
        )

        for item in items:
            self.assertEqual(
                item["material"],
                "copper_ore",
                f"schedule item material should be 'copper_ore' (not fallback 'Ore'), got {item['material']!r}",
            )
            self.assertEqual(
                item["density"],
                1600.0,
                f"schedule item density should be 1600.0 (not fallback 1960.19), got {item['density']}",
            )
            self.assertEqual(
                item["density"],
                catalog_entry["density"],
                "schedule item density must match catalog entry density",
            )


def _collect_zone_material_refs(des):
    """Walk des_inputs for load-zone 'material' ref lists."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("material"), list):
                found.extend(o["material"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(des)
    return found


def _collect_schedule_items(des):
    """Walk des_inputs for material-SCHEDULE items.

    Schedule items are dicts with ALL of:
      - "material" as a plain string (not a list like load-zone refs)
      - "num_of_hauler" key  (present on schedule data rows, absent on catalog entries)
      - "hauler_group_id" key

    Path: des["operations"]["material_schedules"]["all_material_schedule"][*]["data"][*]
    """
    found = []

    def walk(o):
        if isinstance(o, dict):
            if (
                isinstance(o.get("material"), str)
                and "num_of_hauler" in o
                and "hauler_group_id" in o
            ):
                found.append(o)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(des)
    return found


import inspect
import json


class TestGoldenStability(unittest.TestCase):
    def test_only_material_fields_carry_material_data(self):
        model = {
            "nodes": [],
            "roads": [],
            "load_zones": [{"id": 1, "name": "LZ1"}],
            "dump_zones": [{"id": 1, "name": "DZ1"}],
        }
        des = sg.create_des_inputs(
            model,
            machines={},
            site_name="S",
            material="copper_ore",
            density=1600.0,
        )
        # catalog coherent: exactly one entry with the correct compound key
        self.assertEqual(
            list(des["material_properties"].keys()),
            ["copper_ore_1600"],
            "material_properties must contain exactly one entry: copper_ore_1600",
        )
        # no legacy literal values survive anywhere in the emitted dict
        blob = json.dumps(des)
        self.assertNotIn(
            "Ore_1700",
            blob,
            "Legacy literal 'Ore_1700' must not appear in emitted des_inputs",
        )
        self.assertNotIn(
            "Waste_1800",
            blob,
            "Legacy literal 'Waste_1800' must not appear in emitted des_inputs",
        )
        self.assertNotIn(
            "1960.19",
            blob,
            "Legacy fallback literal '1960.19' must not appear in emitted des_inputs "
            "(copper_ore path density=1600.0 should never emit the fallback constant)",
        )
        # every zone material ref resolves to a key in material_properties
        for ref in _collect_zone_material_refs(des):
            self.assertIn(
                ref,
                des["material_properties"],
                f"Zone material ref {ref!r} does not resolve to any material_properties key",
            )


class TestProcessSiteMaterial(unittest.TestCase):
    def test_process_site_accepts_material_param(self):
        sig = inspect.signature(sg.process_site)
        self.assertIn("material", sig.parameters)
        self.assertEqual(sig.parameters["material"].default, sg.DEFAULT_MATERIAL)

    def test_create_operations_structure_threads_density(self):
        # default material/density should appear in schedule items via the wrapper
        items = sg.create_material_schedule_data(
            routes=[{"id": 1, "load_zone": 1, "dump_zone": 1, "name": "R1"}],
            load_zones=[{"id": 1, "name": "LZ1"}],
            dump_zones=[{"id": 1, "name": "DZ1"}],
            haulers=[{"group_id": 1, "number_of_haulers": 1}],
            default_material="copper_ore",
            default_density=1600.0,
        )
        for it in items:
            self.assertEqual(it["material"], "copper_ore")
            self.assertEqual(it["density"], 1600.0)


class TestValidateMaterialNameNullGuard(unittest.TestCase):
    """E-2: null/blank name entries in the materials list must never be selectable
    or appear in the valid-names error message."""

    def _materials_with_null(self):
        """A materials dict that contains one valid entry and one with name=None."""
        return {
            "materials": [
                {"name": None, "loose_density_tpm3": 1.0},
                {"name": "", "loose_density_tpm3": 1.0},
                {"name": "copper_ore", "loose_density_tpm3": 1.6},
            ]
        }

    def test_real_name_still_validates_with_null_entries(self):
        """validate_material_name on 'copper_ore' must succeed even when the list
        contains a None-name entry."""
        materials = self._materials_with_null()
        result = sg.validate_material_name("copper_ore", materials)
        self.assertEqual(result, "copper_ore")

    def test_null_name_not_selectable(self):
        """A None-name entry must not be matched and must not appear in valid names."""
        materials = self._materials_with_null()
        with self.assertRaises(ValueError) as ctx:
            sg.validate_material_name("None", materials)
        error_msg = str(ctx.exception)
        self.assertNotIn('"None"', error_msg)
        self.assertNotIn("None", error_msg.split("Valid materials:")[-1])

    def test_blank_name_not_selectable(self):
        """A blank-string name entry must not be matched or listed as valid."""
        materials = self._materials_with_null()
        with self.assertRaises(ValueError) as ctx:
            sg.validate_material_name("", materials)
        error_msg = str(ctx.exception)
        # The valid names list after "Valid materials:" should not contain an empty token
        after_colon = error_msg.split("Valid materials:")[-1]
        valid_names = [n.strip() for n in after_colon.split(",") if n.strip()]
        self.assertNotIn("", valid_names)

    def test_valid_names_list_excludes_null_and_blank(self):
        """The valid-names list in the error must only contain 'copper_ore'."""
        materials = self._materials_with_null()
        with self.assertRaises(ValueError) as ctx:
            sg.validate_material_name("unknown_material", materials)
        error_msg = str(ctx.exception)
        after_colon = error_msg.split("Valid materials:")[-1]
        valid_names = [n.strip() for n in after_colon.split(",") if n.strip()]
        self.assertEqual(valid_names, ["copper_ore"])


if __name__ == "__main__":
    unittest.main()
