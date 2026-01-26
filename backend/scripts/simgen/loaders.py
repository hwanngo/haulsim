"""
Configuration, path resolution, and data loading utilities — extracted from simulation_generator.py (behavior-preserving).
"""

import copy
import json
import os
import re
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

import msgspec
import numpy as np

from backend.core.db_config import (
    DB_CONFIG,
    DUCKDB_PATH,
    OUTPUT_PATH,
    REFERENCE_DATA_PATH,
)
from backend.scripts.simgen.constants import (
    DEFAULT_CONFIG,
    DEFAULT_MATERIAL_DENSITY,
    TONNES_PER_M3_TO_KG_PER_M3,
)

__all__ = [
    "json_bytes",
    "_enc_hook",
    "resolve_path",
    "backend_dir",
    "scripts_dir",
    "reference_data_resolved",
    "DEFAULT_CONFIG_PATH",
    "MACHINE_TEMPLATES_PATH",
    "MACHINES_LIST_PATH",
    "MATERIALS_PATH",
    "load_config",
    "save_default_config",
    "load_machine_templates",
    "extract_machine_model",
    "load_machines_list",
    "load_materials",
    "_material_entries",
    "_find_material",
    "resolve_material_density",
    "validate_material_name",
    "material_catalog_key",
    "build_material_catalog",
    "build_material_properties",
    "ZoneMaterialResolution",
    "resolve_zone_material_assignment",
    "get_machine_spec_from_list",
    "deep_copy_dict",
    "merge_dict",
]

# Path resolution (loaders.py lives in backend/scripts/simgen/)
_here = os.path.dirname(os.path.abspath(__file__))  # backend/scripts/simgen
scripts_dir = os.path.dirname(_here)  # backend/scripts
backend_dir = os.path.dirname(scripts_dir)  # backend

# Default config file path (relative to scripts_dir, matching original __file__ location)
DEFAULT_CONFIG_PATH = os.path.join(scripts_dir, "config.json")


def resolve_path(path_var, default_relative):
    """Resolve path: if relative, make it relative to backend_dir; if absolute, use as-is."""
    if os.path.isabs(path_var):
        return path_var
    return os.path.join(backend_dir, path_var)


# Machine templates file path (resolved from REFERENCE_DATA_PATH)
reference_data_resolved = resolve_path(REFERENCE_DATA_PATH, "../reference_data")
MACHINE_TEMPLATES_PATH = os.path.join(
    reference_data_resolved, "simulation", "machine_templates.json"
)

# Machines list file path
MACHINES_LIST_PATH = os.path.join(reference_data_resolved, "machines.json")

# Materials reference file
MATERIALS_PATH = os.path.join(reference_data_resolved, "materials.json")


def _enc_hook(obj):
    """Fallback encoder for msgspec.json: numpy scalars -> native, else str
    (parity with the previous json.dumps(default=str))."""
    if isinstance(obj, np.generic):
        return obj.item()
    return str(obj)


def json_bytes(obj, pretty: bool = True) -> bytes:
    """Serialize to JSON bytes with msgspec (fast). Pretty-prints when asked."""
    buf = msgspec.json.encode(obj, enc_hook=_enc_hook)
    return msgspec.json.format(buf, indent=2) if pretty else buf


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to config file. If None, uses default config.json

    Returns:
        Configuration dictionary with all parameters
    """
    config = DEFAULT_CONFIG.copy()

    # Deep copy nested dicts
    config["data_fetching"] = DEFAULT_CONFIG["data_fetching"].copy()
    config["road_detection"] = DEFAULT_CONFIG["road_detection"].copy()
    config["zone_detection"] = DEFAULT_CONFIG["zone_detection"].copy()
    config["simulation"] = DEFAULT_CONFIG["simulation"].copy()

    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)

            # Merge file config into default config
            if "site" in file_config:
                config["site"] = file_config["site"]
            if "output_dir" in file_config:
                config["output_dir"] = file_config["output_dir"]
            if "machine_templates_path" in file_config:
                config["machine_templates_path"] = file_config["machine_templates_path"]

            if "data_fetching" in file_config:
                config["data_fetching"].update(file_config["data_fetching"])
            if "road_detection" in file_config:
                config["road_detection"].update(file_config["road_detection"])
            if "zone_detection" in file_config:
                config["zone_detection"].update(file_config["zone_detection"])
            if "simulation" in file_config:
                config["simulation"].update(file_config["simulation"])

            print(f"  Loaded config from: {config_path}")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"  Warning: Could not load config file ({type(e).__name__}): {e}")
            print("  Using default configuration")
    else:
        print(f"  Config file not found: {config_path}")
        print("  Using default configuration")

    return config


def save_default_config(config_path: str = None):
    """Save default configuration to file."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    with open(config_path, "wb") as f:
        f.write(json_bytes(DEFAULT_CONFIG))

    print(f"Default config saved to: {config_path}")


def load_machine_templates(templates_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load machine templates from JSON file.

    Args:
        templates_path: Path to machine templates file. If None, uses default from env.

    Returns:
        Dictionary containing hauler and loader templates
    """
    if templates_path is None:
        templates_path = MACHINE_TEMPLATES_PATH
    else:
        # Resolve relative path if provided and not absolute
        if not os.path.isabs(templates_path):
            templates_path = os.path.join(backend_dir, templates_path)

    if os.path.exists(templates_path):
        try:
            with open(templates_path, "r", encoding="utf-8") as f:
                templates = json.load(f)
            print(f"  Loaded machine templates from: {templates_path}")
            return templates
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(
                f"  Warning: Could not load machine templates ({type(e).__name__}): {e}"
            )
            print("  Using hardcoded defaults")
    else:
        print(f"  Machine templates file not found: {templates_path}")
        print("  Using hardcoded defaults")

    # Return empty dict to signal using hardcoded defaults
    return {}


def extract_machine_model(type_name: str) -> Optional[str]:
    """
    Extract machine model name from TypeName.

    Examples:
        "Cat798AC CMD" -> "798AC"
        "Cat797F CMD" -> "797F"
        "CAT 793F CMD - Coal" -> "793F"
        "CA_CAT_793F-CMD" -> "793F"
        "930E CMD" -> "930E"
        "777G CMD" -> "777G"

    Args:
        type_name: TypeName from database (e.g., "CAT 793F CMD")

    Returns:
        Machine model name (e.g., "793F") or None if not found
    """
    if not type_name:
        return None

    # Pattern to match model numbers like: 793F, 798AC, 930E, 777G, 785NG, 794AC
    # Model format: 3-4 digits followed by optional letters (F, AC, NG, E, G, D)
    # Note: Don't use \b at start because TypeName may have no space (e.g., "Cat793NG CMD")
    pattern = r"(\d{3,4}[A-Z]{0,3})\b"

    match = re.search(pattern, type_name.upper())
    if match:
        return match.group(1)

    return None


def load_machines_list(machines_list_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load machines list from JSON file.

    The file contains machine specifications indexed by model name (e.g., "793F", "797F").
    Structure is similar to model.json format.

    Args:
        machines_list_path: Path to machines.json file. If None, uses default path.

    Returns:
        Dictionary mapping model name to machine specification data
    """
    if machines_list_path is None:
        machines_list_path = MACHINES_LIST_PATH
    else:
        # Resolve relative path if provided and not absolute
        if not os.path.isabs(machines_list_path):
            machines_list_path = os.path.join(backend_dir, machines_list_path)

    if os.path.exists(machines_list_path):
        try:
            with open(machines_list_path, "r", encoding="utf-8") as f:
                machines_list = json.load(f)
            print(f"  Loaded machines list from: {machines_list_path}")
            return machines_list
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"  Warning: Could not load machines list ({type(e).__name__}): {e}")
            print("  Machine specs will use defaults")
    else:
        print(f"  Machines list file not found: {machines_list_path}")
        print("  Machine specs will use defaults")

    return {}


def load_materials(materials_path: Optional[str] = None) -> Dict[str, Any]:
    """Load reference_data/materials.json. Returns {} (no raise) if absent."""
    if materials_path is None:
        materials_path = MATERIALS_PATH
    elif not os.path.isabs(materials_path):
        materials_path = os.path.join(backend_dir, materials_path)

    if os.path.exists(materials_path):
        try:
            with open(materials_path, "r", encoding="utf-8") as f:
                materials = json.load(f)
            print(f"  Loaded materials from: {materials_path}")
            return materials
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"  Warning: Could not load materials ({type(e).__name__}): {e}")
    else:
        print(f"  Materials file not found: {materials_path}; using default density")
    return {}


def _material_entries(materials: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not materials:
        return []
    raw = materials.get("materials", []) or []
    # Skip entries whose name is falsy (None, "", whitespace-only) so a null/blank
    # name is never a selectable or echoed value (E-2 guard).
    return [e for e in raw if e.get("name") and str(e["name"]).strip()]


def _find_material(
    material_name: str, materials: Optional[Dict[str, Any]]
) -> Optional[Dict]:
    target = (material_name or "").strip().lower()
    for entry in _material_entries(materials):
        if str(entry.get("name", "")).strip().lower() == target:
            return entry
    return None


def resolve_material_density(
    material_name: str, materials: Optional[Dict[str, Any]] = None
) -> float:
    """Loose density in kg/m^3 for material_name from materials.json.

    Falls back to DEFAULT_MATERIAL_DENSITY (with a warning) when the material or
    its loose_density_tpm3 field is missing.
    """
    if materials is None:
        materials = load_materials()
    entry = _find_material(material_name, materials)
    if entry is None:
        print(
            f"  Warning: material '{material_name}' not in materials.json; "
            f"using default density {DEFAULT_MATERIAL_DENSITY}"
        )
        return DEFAULT_MATERIAL_DENSITY
    loose = entry.get("loose_density_tpm3")
    if loose is None:
        print(
            f"  Warning: material '{material_name}' has no loose_density_tpm3; "
            f"using default density {DEFAULT_MATERIAL_DENSITY}"
        )
        return DEFAULT_MATERIAL_DENSITY
    return float(loose) * TONNES_PER_M3_TO_KG_PER_M3


def validate_material_name(material_name: str, materials: Dict[str, Any]) -> str:
    """Return the canonical material name, or raise ValueError listing valid names."""
    entry = _find_material(material_name, materials)
    if entry is not None:
        return str(entry["name"])
    valid = sorted(str(e.get("name")) for e in _material_entries(materials))
    raise ValueError(
        f"Unknown material '{material_name}'. Valid materials: {', '.join(valid)}"
    )


def material_catalog_key(name: str, density: float) -> str:
    """Catalog key '<name>_<int(density)>', e.g. 'copper_ore_1600'."""
    return f"{name}_{int(density)}"


def build_material_catalog(
    materials_with_density: "List[Tuple[str, float]]",
) -> Dict[str, Dict]:
    """Multi-entry des_inputs material_properties catalog.

    `materials_with_density` is a list of (name, density_kg_m3) pairs (duplicates
    allowed; they collapse). Ids are assigned 1..N by SORTED material name so the
    output is deterministic (D-0) and a single material always gets id 1 — keeping
    the default path byte-identical to the pre-multi-material behaviour.
    """
    # Distinct (name, density) by name; a name maps to one density here (the
    # resolver guarantees one density per material).
    by_name: Dict[str, float] = {}
    for name, density in materials_with_density:
        by_name[name] = density
    catalog: Dict[str, Dict] = {}
    for idx, name in enumerate(sorted(by_name), start=1):
        density = by_name[name]
        catalog[material_catalog_key(name, density)] = {
            "id": idx,
            "material": name,
            "density": density,
        }
    return catalog


def build_material_properties(name: str, density: float) -> Dict[str, Dict]:
    """Single-material des_inputs material_properties catalog (back-compat wrapper)."""
    return build_material_catalog([(name, density)])


ZoneMaterialResolution = namedtuple(
    "ZoneMaterialResolution",
    ["catalog", "zone_id_to_key", "zone_name_to_md", "warnings"],
)


def resolve_zone_material_assignment(
    load_zones: "List[Dict]",
    zone_materials: "Optional[Dict[int, str]]",
    site_material: str,
    materials: "Optional[Dict[str, Any]]",
) -> "ZoneMaterialResolution":
    """Resolve each detected load zone to a material and build the catalog.

    - `load_zones`: detected load zones (each has "id" and "name").
    - `zone_materials`: optional {load_zone_id: material_name}; values are assumed
      already validated as known names (app.py validates before the job starts).
      Keys are matched against detected zone ids here.
    - `site_material`: the universal default for any unmapped zone.
    - `materials`: parsed materials.json (for density lookup).

    Returns ZoneMaterialResolution(catalog, zone_id_to_key, zone_name_to_md, warnings).
    An unmatched zone_materials key (a zone id not in `load_zones`) produces a
    warning string and is otherwise ignored (the export still succeeds).
    """
    zm = {int(k): v for k, v in (zone_materials or {}).items()}
    detected_ids = {z["id"] for z in load_zones}

    warnings: List[str] = []
    for zid in sorted(zm):
        if zid not in detected_ids:
            warnings.append(
                f"zone_materials key {zid} does not match any detected load zone; "
                f"that mapping is ignored (the zone, if any, uses the site default '{site_material}')"
            )

    # Per-zone material name (mapped value if the zone is mapped, else site default).
    zone_id_to_material: Dict[int, str] = {}
    density_cache: Dict[str, float] = {}
    for zone in load_zones:
        zid = zone["id"]
        mat = zm.get(zid, site_material)
        zone_id_to_material[zid] = mat
        if mat not in density_cache:
            density_cache[mat] = resolve_material_density(mat, materials)

    catalog = build_material_catalog(
        [(mat, density_cache[mat]) for mat in zone_id_to_material.values()]
    )

    zone_id_to_key: Dict[int, str] = {
        zid: material_catalog_key(mat, density_cache[mat])
        for zid, mat in zone_id_to_material.items()
    }
    zone_name_to_md: Dict[str, "Tuple[str, float]"] = {
        zone["name"]: (
            zone_id_to_material[zone["id"]],
            density_cache[zone_id_to_material[zone["id"]]],
        )
        for zone in load_zones
    }
    return ZoneMaterialResolution(catalog, zone_id_to_key, zone_name_to_md, warnings)


def get_machine_spec_from_list(
    type_name: str, machines_list: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Get machine specification from machines_list by TypeName.

    The machines_list has format:
    {
        "version": "...",
        "machine_list": {
            "haulers": [
                {"id": 1, "name": "777G", ...},
                {"id": 2, "name": "793F", ...}
            ],
            "loaders": [...]
        }
    }

    Args:
        type_name: TypeName from database (e.g., "CAT 793F CMD")
        machines_list: Dictionary loaded from machines.json

    Returns:
        Machine specification dict or None if not found
    """
    if not machines_list:
        return None

    model_name = extract_machine_model(type_name)
    if not model_name:
        return None

    # Get haulers array from machine_list
    machine_list_data = machines_list.get("machine_list", {})
    haulers = machine_list_data.get("haulers", [])

    # Search for hauler by name (exact match first)
    for hauler in haulers:
        if hauler.get("name") == model_name:
            return hauler

    # Try case-insensitive match
    model_name_upper = model_name.upper()
    for hauler in haulers:
        hauler_name = hauler.get("name", "")
        if hauler_name.upper() == model_name_upper:
            return hauler

    return None


def deep_copy_dict(d: Dict) -> Dict:
    """Deep copy a dictionary (handles nested dicts and lists)."""
    return copy.deepcopy(d)


def merge_dict(base: Dict, overrides: Dict) -> Dict:
    """
    Merge overrides into base dict recursively.

    Args:
        base: Base dictionary
        overrides: Dictionary with values to override

    Returns:
        Merged dictionary
    """
    result = deep_copy_dict(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = (
                deep_copy_dict(value) if isinstance(value, (dict, list)) else value
            )
    return result
