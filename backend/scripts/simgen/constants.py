"""
Simulation generator constants — extracted from simulation_generator.py (behavior-preserving).
"""

from typing import Any, Dict

__all__ = [
    "DEFAULT_CONFIG",
    "NODE_MERGE_TOLERANCE_M",
    "ZONE_TO_ROAD_MAX_DIST_M",
    "READER_ZONE_TO_ROAD_MAX_DIST_M",
    "TRANSITION_TO_ZONE_MAX_DIST_M",
    "LOADED_PAYLOAD_THRESHOLD",
    "STOPPED_SPEED_THRESHOLD",
    "DEFAULT_MATERIAL_DENSITY",
    "DEFAULT_MATERIAL",
    "TONNES_PER_M3_TO_KG_PER_M3",
    "HAULER_UID_BASE",
    "MAX_REASONABLE_COORD_M",
]

# Default configuration values
DEFAULT_CONFIG: Dict[str, Any] = {
    "site": None,
    "output_dir": None,  # Will use OUTPUT_PATH from env if None
    "machine_templates_path": None,  # Use default if None
    "data_fetching": {
        "limit": 100000,
        "sample_interval": 5,
    },
    "road_detection": {
        "grid_size": 5.0,
        "min_density": 3,
        "simplify_epsilon": 5.0,
        "max_node_distance": 500.0,
        "merge_tolerance": 15.0,
    },
    "zone_detection": {
        "grid_size": 10.0,
        "min_stop_count": 20,
    },
    "simulation": {
        "sim_time": 480,
    },
}


# =============================================================================
# Named constants (L13 - promoted from magic numbers)
# =============================================================================

# Spatial de-duplication tolerance for road nodes (meters). Two trajectory
# points closer than this collapse to a single node.
NODE_MERGE_TOLERANCE_M = 5.0

# Maximum distance (meters) a detected zone centroid may be from the nearest
# road endpoint before the zone is rejected. Two call sites historically used
# different caps, preserved here as separate constants.
ZONE_TO_ROAD_MAX_DIST_M = 100.0  # grid-based detect_zones()
READER_ZONE_TO_ROAD_MAX_DIST_M = 200.0  # Reader.py zone conversion

# Maximum distance (meters) a load/dump transition may be from a zone center
# when matching telemetry transitions to zones.
TRANSITION_TO_ZONE_MAX_DIST_M = 500.0

# Payload percentage at/above which a truck is considered "loaded" when
# classifying load/dump zones and detecting load/dump transitions.
LOADED_PAYLOAD_THRESHOLD = 50.0

# Speed (m/s or model units) at/below which a telemetry point counts as a stop.
STOPPED_SPEED_THRESHOLD = 5

# Default material density (kg/m^3) used only as a fallback when a material or
# its loose_density_tpm3 field is absent from materials.json.
DEFAULT_MATERIAL_DENSITY = 1960.19
# Default material name (must be a real reference_data/materials.json entry).
DEFAULT_MATERIAL = "copper_ore"
# materials.json densities are tonnes/m^3; the DES output contract is kg/m^3.
TONNES_PER_M3_TO_KG_PER_M3 = 1000.0

# Base value added to per-machine ids to form unique hauler "uid" values.
HAULER_UID_BASE = 200

# Coordinate magnitude (meters) above which "meters" mode is almost certainly
# wrong (e.g. millimetre data mislabelled as meters -> 1000x mis-scale).
MAX_REASONABLE_COORD_M = 1e7
