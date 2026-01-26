"""Facade namespace contract for sub-project D (decomposition).

After `simulation_generator.py` becomes a thin facade that re-exports the `simgen/`
package, `import simulation_generator as sg` must still expose every public name
that app.py and the test suite rely on. This guards the `from simgen.X import *`
re-export contract so a missing `__all__` entry fails loudly instead of as an
AttributeError on an untested path.
"""

import os
import sys
import unittest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(BACKEND_DIR, "..")))
sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))

import simulation_generator as sg  # noqa: E402

# app.py's import set (must stay importable from the facade)
APP_IMPORTS = [
    "get_connection",
    "fetch_sites",
    "fetch_machines",
    "process_site",
    "load_machine_templates",
    "load_machines_list",
    "load_materials",
    "validate_material_name",
    "DEFAULT_CONFIG",
    "DEFAULT_MATERIAL",
]

# Names referenced as sg.* across backend/tests/
TEST_SURFACE = [
    "DEFAULT_MATERIAL_DENSITY",
    "build_material_properties",
    "create_des_inputs",
    "create_material_schedule_data",
    "create_roads_from_trajectories",
    "detect_zones",
    "fetch_telemetry_data",
    "material_catalog_key",
    "resolve_material_density",
    "main",
]


class TestFacadeNamespace(unittest.TestCase):
    def test_public_names_present(self):
        missing = [n for n in APP_IMPORTS + TEST_SURFACE if not hasattr(sg, n)]
        self.assertEqual(missing, [], f"facade missing public names: {missing}")


if __name__ == "__main__":
    unittest.main()
