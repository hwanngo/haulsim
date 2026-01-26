"""
Generate All Simulation Data

Creates both model and simulation files from database telemetry:
1. Model file (nodes, roads, zones) - for road network visualization
2. DES Inputs file - for simulation engine configuration
3. Events Ledger file - for animation playback

Usage:
    python scripts/simulation_generator.py                           # Use config.json
    python scripts/simulation_generator.py --config custom.json      # Use custom config
    python scripts/simulation_generator.py --site "BhpEscondida"     # Override site from CLI
    python scripts/simulation_generator.py --list-sites              # List available sites

Config file (config.json) contains all configurable parameters.
CLI arguments override config file values.
"""

import argparse
import gzip
import os
import sys

from typing import List, Dict, Optional, Tuple, Any, Set
from collections import defaultdict
import math

# Add webapp directory to path for imports
# backend/scripts/simulation_generator.py -> backend/ -> webapp/
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
webapp_root = os.path.dirname(backend_dir)
sys.path.insert(0, webapp_root)

import duckdb

try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    def tqdm(iterable, desc=None, total=None, disable=False):
        return iterable


from backend.core.db_config import (
    DB_CONFIG,
    DUCKDB_PATH,
    OUTPUT_PATH,
    REFERENCE_DATA_PATH,
)
from backend.simulation_analysis import GPSToEventsConverter

try:
    from openpyxl import Workbook

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


from backend.scripts.simgen.constants import *  # noqa: F401, F403
from backend.scripts.simgen.loaders import *  # noqa: F401, F403


from backend.scripts.simgen.db import *  # noqa: F401, F403


# =============================================================================
# Model Generation Functions
# =============================================================================

from backend.scripts.simgen.geometry import *  # noqa: F401, F403


from backend.scripts.simgen.roads import *  # noqa: F401, F403


# NOTE: deliberately kept in the facade (not simgen/roads.py). A test patches
# `sg._warn_coordinate_magnitude` and calls `sg.create_roads_from_trajectories`;
# both must share this module's namespace for the patch to intercept the call.
# Moving it into roads.py would silently break that mock contract. See
# .superpowers/sdd/task-decompose-report.md. roads.py owns graph manipulation
# (merge/split); this function builds the initial graph from raw trajectories.
def create_roads_from_trajectories(
    telemetry_data: List[Tuple],
    simplify_epsilon: float = 10.0,
    min_segment_distance: float = 15.0,
    max_node_distance: float = 500.0,
    coordinates_in_meters: bool = False,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Create road network from actual vehicle trajectories.

    This ensures nodes and roads follow the actual path of vehicles,
    maintaining correct sequence order for animation playback.

    Args:
        telemetry_data: Sorted telemetry data (by machine, cycle, segment, interval)
        simplify_epsilon: Douglas-Peucker simplification threshold (meters)
        min_segment_distance: Minimum distance between nodes (meters)
        max_node_distance: Maximum allowed distance between consecutive nodes (meters).
                          Trajectories are split at gaps exceeding this threshold.
        coordinates_in_meters: If True, coordinates are already in meters (for imported data).
                              If False, coordinates are in millimeters (for database data).

    Returns:
        Tuple of (nodes list, roads list)
    """
    if not telemetry_data:
        return [], []

    print(f"    Creating roads from trajectories (epsilon={simplify_epsilon}m)...")

    # Group telemetry by machine
    machine_trajectories = {}
    for row in telemetry_data:
        machine_id = row[0]
        # Convert coordinates based on source
        if coordinates_in_meters:
            # Coordinates already in meters (imported data)
            coord = (
                round(float(row[4]), 3),
                round(float(row[5]), 3),
                round(float(row[6]), 3),
            )
        else:
            # Coordinates in millimeters (database data) - convert to meters
            coord = convert_coordinates(row[4], row[5], row[6])

        if machine_id not in machine_trajectories:
            machine_trajectories[machine_id] = []
        machine_trajectories[machine_id].append(coord)

    # H1 magnitude safety: in "meters" mode, flag implausibly large coordinates
    # (a sign that millimetre data was mislabelled and would be 1000x off).
    if coordinates_in_meters and machine_trajectories:
        max_abs_coord = max(
            max(abs(c[0]), abs(c[1]))
            for traj in machine_trajectories.values()
            for c in traj
        )
        if max_abs_coord > MAX_REASONABLE_COORD_M:
            _warn_coordinate_magnitude(max_abs_coord)

    print(f"    Found {len(machine_trajectories)} machine trajectories")

    # Split trajectories at distance gaps exceeding max_node_distance
    # This prevents connecting unrelated trajectory segments (e.g., different cycles)
    split_trajectories = []
    total_splits = 0
    for machine_id, trajectory in machine_trajectories.items():
        current_segment = [trajectory[0]]
        for i in range(1, len(trajectory)):
            dist = calculate_distance(trajectory[i - 1], trajectory[i])
            if dist > max_node_distance:
                # Gap detected - finish current segment and start new one
                if len(current_segment) >= 2:
                    split_trajectories.append(current_segment)
                total_splits += 1
                current_segment = [trajectory[i]]
            else:
                current_segment.append(trajectory[i])
        if len(current_segment) >= 2:
            split_trajectories.append(current_segment)

    if total_splits > 0:
        print(
            f"    Split trajectories at {total_splits} gaps > {max_node_distance}m "
            f"({len(machine_trajectories)} machines -> {len(split_trajectories)} segments)"
        )

    # Create unified node map (avoid duplicate nodes at same location)
    all_nodes = []
    node_id = 1
    # Spatial-hash grid (H7): cell key -> list of (x, y, node_id).
    # Cell size == tolerance, so any node within `tolerance` of a point lies in
    # the point's own cell or one of the 8 neighbours. This replaces the old
    # O(points x nodes) linear scan with an O(points) lookup while preserving
    # merge behavior within tolerance.
    node_grid = defaultdict(list)  # (cell_x, cell_y) -> [(x, y, node_id), ...]

    def get_or_create_node(
        coord: Tuple[float, float, float], tolerance: float = NODE_MERGE_TOLERANCE_M
    ) -> int:
        nonlocal node_id
        x, y, z = coord

        # Check the 9 neighbouring cells for an existing node within tolerance.
        cell_x = round(x / tolerance)
        cell_y = round(y / tolerance)
        tol_sq = tolerance * tolerance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nx, ny, nid in node_grid[(cell_x + dx, cell_y + dy)]:
                    if (x - nx) ** 2 + (y - ny) ** 2 < tol_sq:
                        return nid

        # Create new node
        new_node = {
            "id": node_id,
            "name": f"Node_{node_id}",
            "coords": [x, y, z],
            "speed_limit": 40.0,
            "rolling_resistance": 2.5,
            "banking": 0,
            "curvature": "",
            "lane_width": 14,
            "traction": 0.6,
        }
        all_nodes.append(new_node)
        node_grid[(cell_x, cell_y)].append((x, y, node_id))
        node_id += 1
        return new_node["id"]

    # Create roads from split trajectory segments
    roads_list = []
    road_id = 1

    traj_iter = split_trajectories
    if TQDM_AVAILABLE:
        traj_iter = tqdm(split_trajectories, desc="    Building roads", unit="segment")

    for trajectory in traj_iter:
        if len(trajectory) < 2:
            continue

        # Simplify trajectory using Douglas-Peucker
        simplified = douglas_peucker(trajectory, simplify_epsilon)

        if len(simplified) < 2:
            continue

        # Further filter by minimum segment distance
        filtered_points = [simplified[0]]
        for point in simplified[1:]:
            if calculate_distance(filtered_points[-1], point) >= min_segment_distance:
                filtered_points.append(point)

        # Ensure last point is included
        if len(filtered_points) >= 1 and filtered_points[-1] != simplified[-1]:
            if (
                calculate_distance(filtered_points[-1], simplified[-1])
                >= min_segment_distance / 2
            ):
                filtered_points.append(simplified[-1])

        if len(filtered_points) < 2:
            continue

        # Safety net: split at any remaining gaps > max_node_distance after simplification
        road_segments = []
        current_segment_points = [filtered_points[0]]
        for point in filtered_points[1:]:
            if (
                calculate_distance(current_segment_points[-1], point)
                > max_node_distance
            ):
                if len(current_segment_points) >= 2:
                    road_segments.append(current_segment_points)
                current_segment_points = [point]
            else:
                current_segment_points.append(point)
        if len(current_segment_points) >= 2:
            road_segments.append(current_segment_points)

        # Create roads from each valid segment
        for segment_points in road_segments:
            road_node_ids = []
            for point in segment_points:
                nid = get_or_create_node(point)
                # Avoid consecutive duplicates
                if not road_node_ids or road_node_ids[-1] != nid:
                    road_node_ids.append(nid)

            if len(road_node_ids) >= 2:
                road = {
                    "id": road_id,
                    "name": f"Road_{road_id}",
                    "nodes": road_node_ids,
                    "is_generated": False,
                    "ways_num": 2,
                    "lanes_num": 1,
                    "banking": "",
                    "lane_width": "",
                    "speed_limit": "",
                    "rolling_resistance": "",
                    "traction_coefficient": "",
                    "offset": 0,
                }
                roads_list.append(road)
                road_id += 1

    print(
        f"    Created {len(all_nodes)} nodes and {len(roads_list)} roads from trajectories"
    )

    # Cleanup: Remove unused nodes (nodes not referenced by any road)
    used_node_ids = set()
    for road in roads_list:
        used_node_ids.update(road["nodes"])

    original_node_count = len(all_nodes)
    all_nodes = [node for node in all_nodes if node["id"] in used_node_ids]

    if len(all_nodes) < original_node_count:
        print(f"    Cleaned up {original_node_count - len(all_nodes)} unused nodes")

    return all_nodes, roads_list


from backend.scripts.simgen.zones import *  # noqa: F401, F403
from backend.scripts.simgen.routes import *  # noqa: F401, F403
from backend.scripts.simgen.operations import *  # noqa: F401, F403
from backend.scripts.simgen.model import *  # noqa: F401, F403
from backend.scripts.simgen.specs import *  # noqa: F401, F403

from backend.scripts.simgen.des import *  # noqa: F401, F403

# =============================================================================
# Main Processing Function
# =============================================================================


def process_site(
    cursor,
    site_name: str,
    machines: Dict[int, Dict],
    output_dir: Optional[str] = None,
    limit: int = 100000,
    sample_interval: int = 5,
    grid_size: float = 5.0,  # DEPRECATED/unused: kept only for caller compatibility (app.py)
    min_density: int = 3,  # DEPRECATED/unused: kept only for caller compatibility (app.py)
    simplify_epsilon: float = 5.0,
    max_node_distance: float = 500.0,
    merge_tolerance: float = 15.0,
    zone_grid_size: float = 10.0,
    zone_min_stops: int = 20,
    sim_time: int = 480,
    machine_templates: Optional[Dict[str, Any]] = None,
    machines_list: Optional[Dict[str, Any]] = None,
    telemetry_data: Optional[List[Tuple]] = None,
    coordinates_in_meters: Optional[bool] = None,
    precomputed_zones: Optional[List] = None,
    output_base_name: Optional[str] = None,
    export_model: bool = True,
    export_simulation: bool = True,
    export_routes_excel: bool = False,
    material: str = DEFAULT_MATERIAL,
    zone_materials: Optional[Dict[int, str]] = None,
) -> Dict[str, str]:
    """
    Process site data and generate all output files.

    Args:
        cursor: Database cursor (can be None if telemetry_data is provided)
        site_name: Site name
        machines: Dictionary of machine information
        output_dir: Output directory path
        limit: Limit for data fetching (ignored if telemetry_data provided)
        sample_interval: Sample interval (ignored if telemetry_data provided)
        grid_size: DEPRECATED, unused. Fed only the removed legacy
                   detect_road_network() path. Retained for caller compatibility.
        min_density: DEPRECATED, unused. See grid_size.
        simplify_epsilon: Simplify epsilon for road detection
        max_node_distance: Maximum allowed distance between consecutive road nodes (meters)
        zone_grid_size: Grid size for zone detection
        zone_min_stops: Minimum stops for zone detection
        sim_time: Simulation time
        machine_templates: Machine templates dictionary
        machines_list: Machine specifications by model name (e.g., "793F" -> spec data)
        telemetry_data: Optional pre-fetched telemetry data (list of tuples)
        coordinates_in_meters: If True, coordinates are in meters (import flow).
                              If False, coordinates are in millimeters (database flow).
                              If None, will be determined based on data source.
        precomputed_zones: Optional list of Reader.Zone objects from parse_cp1_data.
                          If provided, uses these instead of detect_zones().
        output_base_name: Optional base name for output files (e.g., "ABC" -> "ABC_model.json").
                         If not provided, uses site_name.
        export_model: If True, generate model.json file.
        export_simulation: If True, generate des_inputs.json.gz and ledger.json.gz files.
        export_routes_excel: If True, generate routes.xlsx file (Route_Template format).

    Returns:
        Dictionary with paths to generated files
    """
    # Use OUTPUT_PATH from env if output_dir not provided
    if output_dir is None:
        output_dir = resolve_path(OUTPUT_PATH, "../output")
        os.makedirs(output_dir, exist_ok=True)

    # Get machine IDs for this site
    machine_ids = [
        m["machine_unique_id"]
        for m in machines.values()
        if m.get("site_name") == site_name
    ]

    if not machine_ids and not telemetry_data:
        print(f"  No machines found for site: {site_name}")
        return {}

    print(f"\n  Processing site: {site_name} ({len(machine_ids)} machines)")

    # Track whether the data was fetched by us from the DB (always millimetres)
    # vs supplied by the caller (unit determined by coordinates_in_meters).
    fetched_from_db = telemetry_data is None

    # Fetch telemetry data or use provided data
    if telemetry_data is not None:
        print("  [1/5] Using provided telemetry data...")
        print(f"    Using {len(telemetry_data):,} records")
        # Extract unique machine IDs from telemetry data. Sort them: the import
        # (provided-telemetry) path inserts these into the machines dict, whose
        # iteration order drives hauler id/group_id assignment. Without sorting,
        # set iteration order would make the import-path export nondeterministic.
        if telemetry_data:
            unique_machine_ids = sorted(set(row[0] for row in telemetry_data))
            machine_ids = list(unique_machine_ids)
            # Create minimal machine info for machines in telemetry data
            for mid in unique_machine_ids:
                if mid not in machines:
                    machines[mid] = {
                        "machine_unique_id": mid,
                        "name": f"Machine_{mid}",
                        "site_name": site_name,
                        "type_name": "Unknown",
                    }
    else:
        print("  [1/5] Fetching telemetry data...")
        telemetry_data = fetch_telemetry_data(
            cursor,
            machine_ids=machine_ids,
            limit=limit,
            sample_interval=sample_interval,
        )

        if not telemetry_data:
            print(f"  No telemetry data found for site: {site_name}")
            return {}

        print(f"    Fetched {len(telemetry_data):,} records")

    # Generate model (nodes and roads) from actual trajectories
    print("  [2/5] Generating road network model from trajectories...")
    # H1: Determine the coordinate unit EXPLICITLY rather than inferring it from
    # "was data passed in". Rules, in priority order:
    #   1. If the caller passed coordinates_in_meters, always honour it
    #      (the live import path passes True and is unaffected).
    #   2. If we fetched the data ourselves from the DB, it is millimetres.
    #   3. If pre-fetched data was passed WITHOUT a unit flag, we cannot know
    #      the unit for certain -> assume millimetres (the DB convention, the
    #      conservative default) and rely on the magnitude safety check in
    #      create_roads_from_trajectories to flag a mis-scale.
    if coordinates_in_meters is None:
        if fetched_from_db:
            coordinates_in_meters = False
        else:
            print(
                "    WARNING: telemetry_data passed without coordinates_in_meters; "
                "assuming millimetres (DB convention). Pass the flag explicitly to "
                "avoid this ambiguity."
            )
            coordinates_in_meters = False
    print(f"    coordinates_in_meters = {coordinates_in_meters}")

    # Resolve material density once for both model and DES builders
    materials = load_materials()
    material = validate_material_name(material, materials) if materials else material
    material_density = resolve_material_density(material, materials)

    nodes, roads = create_roads_from_trajectories(
        telemetry_data,
        simplify_epsilon=simplify_epsilon,
        min_segment_distance=15.0,
        max_node_distance=max_node_distance,
        coordinates_in_meters=coordinates_in_meters,
    )

    if not nodes or not roads:
        print("  Error: Could not generate road network")
        return {}

    # Merge geometrically overlapping roads before splitting
    nodes, roads = merge_overlapping_roads(
        nodes, roads, merge_tolerance=merge_tolerance
    )

    # Split roads at intersections and overlaps
    # This ensures roads only share nodes at endpoints
    roads, road_composition = split_roads_at_intersections(roads)
    print(f"    After splitting: {len(roads)} road segments")

    # Detect zones
    print("  [3/5] Detecting load/dump zones...")
    if precomputed_zones is not None:
        print(
            "    Using precomputed zones from Reader.py (Segment classification + DBSCAN)..."
        )
        load_zones, dump_zones = convert_reader_zones_to_model(
            precomputed_zones, nodes, roads
        )
        print(
            f"    Reader.py: {len(load_zones)} load zones, {len(dump_zones)} dump zones"
        )

        # Supplement with detect_zones() to catch zones Reader.py missed
        if telemetry_data:
            print("    Running supplementary grid-based zone detection...")
            sup_load, sup_dump = detect_zones(
                telemetry_data,
                nodes,
                roads,
                zone_grid_size,
                zone_min_stops,
                coordinates_in_meters=coordinates_in_meters,
            )
            # Merge non-duplicate zones (skip if within 100m of existing zone)
            merge_dist = 100.0
            for sz in sup_load:
                sl = sz.get("detected_location", {})
                sx, sy = sl.get("x", 0), sl.get("y", 0)
                is_dup = False
                for ez in load_zones:
                    el = ez.get("detected_location", {})
                    dx = sx - el.get("x", 0)
                    dy = sy - el.get("y", 0)
                    if math.sqrt(dx * dx + dy * dy) < merge_dist:
                        is_dup = True
                        break
                if not is_dup:
                    sz["id"] = len(load_zones) + 1
                    sz["name"] = f"Load zone {sz['id']}"
                    load_zones.append(sz)

            for sz in sup_dump:
                sl = sz.get("detected_location", {})
                sx, sy = sl.get("x", 0), sl.get("y", 0)
                is_dup = False
                for ez in dump_zones:
                    el = ez.get("detected_location", {})
                    dx = sx - el.get("x", 0)
                    dy = sy - el.get("y", 0)
                    if math.sqrt(dx * dx + dy * dy) < merge_dist:
                        is_dup = True
                        break
                if not is_dup:
                    sz["id"] = len(dump_zones) + 1
                    sz["name"] = f"Dump zone {sz['id']}"
                    dump_zones.append(sz)

            # L2: removed unused added_load/added_dump computations here.
            if sup_load or sup_dump:
                print(
                    f"    Supplementary: found {len(sup_load)} load, {len(sup_dump)} dump candidates"
                )
    else:
        load_zones, dump_zones = detect_zones(
            telemetry_data,
            nodes,
            roads,
            zone_grid_size,
            zone_min_stops,
            coordinates_in_meters=coordinates_in_meters,
        )
    print(f"    Total: {len(load_zones)} load zones, {len(dump_zones)} dump zones")

    # Per-zone material resolution (G). With no zone_materials this yields the
    # single site-wide material and a 1-entry catalog — byte-identical to before.
    from backend.scripts.simgen.loaders import resolve_zone_material_assignment

    _zone_res = resolve_zone_material_assignment(
        load_zones, zone_materials, material, materials
    )
    for _w in _zone_res.warnings:
        print(f"  Warning: {_w}")

    # Create model with machine_list from machines.json
    model = create_model(
        nodes,
        roads,
        load_zones,
        dump_zones,
        machines=machines,
        machines_list=machines_list,
        telemetry_data=telemetry_data,
        coordinates_in_meters=coordinates_in_meters,
        material=material,
        density=material_density,
        zone_material_map=_zone_res.zone_name_to_md,
    )

    # Generate events and DES inputs (only if export_simulation is True)
    all_events = []
    des_inputs = {}
    machines_with_events: Set[int] = set()

    if export_simulation:
        print("  [4/5] Generating simulation events...")
        converter = GPSToEventsConverter(model_data=model)

        machine_data = {}
        for row in telemetry_data:
            mid = row[0]
            if mid not in machine_data:
                machine_data[mid] = []
            machine_data[mid].append(row)

        machine_iterator = machine_data.items()
        if TQDM_AVAILABLE:
            machine_iterator = tqdm(
                list(machine_iterator), desc="    Machines", unit="machine"
            )

        for machine_id, data in machine_iterator:
            machine_info = machines.get(machine_id, {})
            machine_name = machine_info.get("name", f"Machine_{machine_id}")

            events = converter.convert_raw_telemetry(
                data,
                machine_id=machine_id,
                machine_name=machine_name,
                # Use smaller node spacing and larger search radius
                # so haulers follow more nodes along the road network.
                min_node_distance=5.0,
                max_search_distance=150.0,
                # Pass coordinates_in_meters to ensure consistent unit conversion
                # between road creation and event generation
                coordinates_in_meters=coordinates_in_meters,
            )

            # Only keep machines that actually generated events
            if events:
                machines_with_events.add(machine_id)
                all_events.extend(events)

            converter.reset()

        # Sort events by time and renumber
        all_events.sort(key=lambda e: (e.get("time", 0), e.get("eid", 0)))

        # Normalize time to start from 0 (all times in minutes from simulation start)
        if all_events:
            min_time = min(e.get("time", 0) for e in all_events)
            for event in all_events:
                event["time"] = round(event["time"] - min_time, 4)

        # Renumber events after sorting
        for i, event in enumerate(all_events):
            event["eid"] = i + 1

        print(f"    Generated {len(all_events):,} events")

        # Generate DES Inputs - only include machines that have events
        print("  [5/5] Generating DES inputs...")
        des_inputs = create_des_inputs(
            model,
            machines,
            site_name,
            sim_time,
            machines_with_events,
            machine_templates,
            telemetry_data=telemetry_data,
            coordinates_in_meters=coordinates_in_meters,
            material=material,
            density=material_density,
            material_catalog=_zone_res.catalog,
            zone_id_to_key=_zone_res.zone_id_to_key,
            zone_material_map=_zone_res.zone_name_to_md,
        )
    else:
        print("  [4/5] Skipping simulation events (export_simulation=False)")
        print("  [5/5] Skipping DES inputs (export_simulation=False)")

    # Save files based on export options
    # Use output_base_name if provided, otherwise use site_name
    file_base = output_base_name if output_base_name else site_name
    safe_name = file_base.replace(" ", "_").replace("/", "_").replace("\\", "_")
    os.makedirs(output_dir, exist_ok=True)

    result = {}
    print(f"\n  Output files saved to: {output_dir}", flush=True)

    # Save model (if export_model is True)
    if export_model:
        model_path = os.path.join(output_dir, f"{safe_name}_model.json")
        with open(model_path, "wb") as f:
            f.write(json_bytes(model))
        result["model"] = model_path
        print(
            f"    - Model: {safe_name}_model.json ({len(nodes)} nodes, {len(roads)} roads)",
            flush=True,
        )

    # Export route data to Excel (Route_Template format) - requires model data
    if export_routes_excel:
        routes = model.get("routes", [])
        route_excel_path = os.path.join(output_dir, f"{safe_name}_routes.xlsx")
        excel_result = export_route_excel(
            nodes, roads, load_zones, dump_zones, routes, route_excel_path
        )
        if excel_result:
            result["routes_excel"] = excel_result
            print(
                f"    - Routes Excel: {safe_name}_routes.xlsx ({len(routes)} routes)",
                flush=True,
            )

    # Save simulation files (if export_simulation is True)
    if export_simulation:
        # Save DES inputs (gzip compressed)
        des_inputs_path = os.path.join(output_dir, f"{safe_name}_des_inputs.json.gz")
        with gzip.open(des_inputs_path, "wb") as f:
            f.write(json_bytes(des_inputs, pretty=False))
        result["des_inputs"] = des_inputs_path
        print(
            f"    - DES Inputs: {safe_name}_des_inputs.json.gz ({len(des_inputs['haulers'])} haulers)",
            flush=True,
        )

        # Save events ledger
        events_output = {
            "status": True,
            "data": {
                "version": "20250818",
                "events": all_events,
                "summary": {
                    "total_events": len(all_events),
                    "total_haulers": len(machine_data),
                    "simulation_duration_minutes": max(
                        (e.get("time", 0) for e in all_events), default=0
                    ),
                },
            },
        }
        # Save events ledger (gzip compressed)
        ledger_path = os.path.join(output_dir, f"{safe_name}_ledger.json.gz")
        with gzip.open(ledger_path, "wb") as f:
            f.write(json_bytes(events_output, pretty=False))
        result["ledger"] = ledger_path
        print(
            f"    - Events Ledger: {safe_name}_ledger.json.gz ({len(all_events)} events)",
            flush=True,
        )

    print(f"\n  [process_site] Returning result: {list(result.keys())}", flush=True)
    return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate model and simulation files from AMT telemetry data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/simulation_generator.py                        # Use config.json
  python scripts/simulation_generator.py --config custom.json   # Use custom config
  python scripts/simulation_generator.py --site "BhpEscondida"  # Override site
  python scripts/simulation_generator.py --all-sites            # Process ALL sites
  python scripts/simulation_generator.py --list-sites           # List available sites
  python scripts/simulation_generator.py --init-config          # Create default config.json

Config file parameters can be overridden by CLI arguments.
        """,
    )

    # Config file argument
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config JSON file (default: scripts/config.json)",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create default config.json and exit",
    )

    # Override arguments (all optional, will use config if not provided)
    parser.add_argument(
        "--site",
        type=str,
        default=None,
        help="Site name to process (overrides config)",
    )
    parser.add_argument(
        "--list-sites",
        action="store_true",
        help="List available sites and exit",
    )
    parser.add_argument(
        "--all-sites",
        action="store_true",
        help="Process ALL available sites",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (overrides config)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum telemetry records to fetch (overrides config)",
    )
    parser.add_argument(
        "--sample-interval",
        type=int,
        default=None,
        help="Sample every Nth record (overrides config)",
    )
    parser.add_argument(
        "--grid-size",
        type=float,
        default=None,
        help="Grid cell size for road detection in meters (overrides config)",
    )
    parser.add_argument(
        "--min-density",
        type=int,
        default=None,
        help="Minimum point density for road detection (overrides config)",
    )
    parser.add_argument(
        "--sim-time",
        type=int,
        default=None,
        help="Simulation time in minutes (overrides config)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("GENERATE ALL SIMULATION DATA")
    print("=" * 70)

    # Handle --init-config
    if args.init_config:
        save_default_config(args.config)
        return

    # Load configuration
    print("\n[0/3] Loading configuration...")
    config = load_config(args.config)

    # Override config with CLI arguments
    site = args.site if args.site is not None else config["site"]
    # Use OUTPUT_PATH from env if not specified
    if args.output_dir is not None:
        output_dir = args.output_dir
    elif "output_dir" in config and config["output_dir"]:
        output_dir = config["output_dir"]
    else:
        output_dir = resolve_path(OUTPUT_PATH, "../output")
    machine_templates_path = config.get(
        "machine_templates_path"
    )  # Path to custom templates
    limit = args.limit if args.limit is not None else config["data_fetching"]["limit"]
    sample_interval = (
        args.sample_interval
        if args.sample_interval is not None
        else config["data_fetching"]["sample_interval"]
    )
    grid_size = (
        args.grid_size
        if args.grid_size is not None
        else config["road_detection"]["grid_size"]
    )
    min_density = (
        args.min_density
        if args.min_density is not None
        else config["road_detection"]["min_density"]
    )
    simplify_epsilon = config["road_detection"]["simplify_epsilon"]
    max_node_distance = config["road_detection"]["max_node_distance"]
    merge_tolerance = config["road_detection"].get("merge_tolerance", 15.0)
    zone_grid_size = config["zone_detection"]["grid_size"]
    zone_min_stops = config["zone_detection"]["min_stop_count"]
    sim_time = (
        args.sim_time if args.sim_time is not None else config["simulation"]["sim_time"]
    )

    # Print effective configuration
    print("\n  Effective configuration:")
    print(f"    site: {site}")
    print(f"    output_dir: {output_dir}")
    print(f"    data_fetching.limit: {limit}")
    print(f"    data_fetching.sample_interval: {sample_interval}")
    print(f"    road_detection.grid_size: {grid_size}")
    print(f"    road_detection.min_density: {min_density}")
    print(f"    road_detection.simplify_epsilon: {simplify_epsilon}")
    print(f"    road_detection.max_node_distance: {max_node_distance}")
    print(f"    road_detection.merge_tolerance: {merge_tolerance}")
    print(f"    zone_detection.grid_size: {zone_grid_size}")
    print(f"    zone_detection.min_stop_count: {zone_min_stops}")
    print(f"    simulation.sim_time: {sim_time}")

    print(f"\nDatabase (DuckDB): {DB_CONFIG['path']}")

    # Connect to database
    print("\n[1/3] Connecting to database...")
    connection = get_connection()
    if not connection:
        print("Failed to connect to database")
        return

    # C2: bind cursor before the try so the finally can guard it. If
    # connection.cursor() raises, cursor stays None and the finally won't throw
    # a NameError that masks the real error.
    cursor = None
    try:
        cursor = connection.cursor()

        # Fetch sites
        print("[2/3] Fetching site information...")
        sites = fetch_sites(cursor)
        print(f"  Found {len(sites)} sites")

        if args.list_sites:
            print("\nAvailable sites:")
            print("-" * 40)
            for s in sites:
                short = s["site_short"] or "N/A"
                print(f"  {s['site_name']} ({short})")
            print("-" * 40)
            return

        # Determine which sites to process
        site_names = [s["site_name"] for s in sites]

        if args.all_sites:
            # Process all sites
            sites_to_process = site_names
            print(f"\n  Processing ALL {len(sites_to_process)} sites...")
        elif site:
            # Process single site
            if site not in site_names:
                print(f"\nError: Site '{site}' not found.")
                print("Available sites:", ", ".join(site_names))
                return
            sites_to_process = [site]
        else:
            print("\nError: Site is required.")
            print(
                "  Set 'site' in config.json, use --site argument, or use --all-sites."
            )
            print("  Use --list-sites to see available sites.")
            return

        # Process each site
        print("[3/3] Processing...")
        all_results = {}
        failed_sites = []

        # Load machine templates
        machine_templates = load_machine_templates(machine_templates_path)
        machines_list = load_machines_list()

        for idx, site_name in enumerate(sites_to_process, 1):
            if len(sites_to_process) > 1:
                print(f"\n{'=' * 70}")
                print(f"  Site {idx}/{len(sites_to_process)}: {site_name}")
                print(f"{'=' * 70}")

            machines = fetch_machines(cursor, site_name)

            result = process_site(
                cursor,
                site_name,
                machines,
                output_dir,
                limit=limit,
                sample_interval=sample_interval,
                grid_size=grid_size,
                min_density=min_density,
                simplify_epsilon=simplify_epsilon,
                max_node_distance=max_node_distance,
                merge_tolerance=merge_tolerance,
                zone_grid_size=zone_grid_size,
                zone_min_stops=zone_min_stops,
                sim_time=sim_time,
                machine_templates=machine_templates,
                machines_list=machines_list,
            )

            if result:
                all_results[site_name] = result
            else:
                failed_sites.append(site_name)

        # Print summary
        print("\n" + "=" * 70)
        print("GENERATION COMPLETE")
        print("=" * 70)

        if all_results:
            print(f"\nSuccessfully processed {len(all_results)} site(s):")
            for site_name, result in all_results.items():
                print(f"\n  {site_name}:")
                for key, path in result.items():
                    print(f"    {key}: {path}")

        if failed_sites:
            print(f"\nFailed sites ({len(failed_sites)}):")
            for site_name in failed_sites:
                print(f"  - {site_name}")

        print("=" * 70)

    except (duckdb.Error, OSError, ValueError, KeyError) as e:
        # M9: narrowed from bare Exception. DB errors, file IO, and data-shape
        # problems are expected here; anything else propagates (the finally
        # below still cleans up the cursor/connection).
        print(f"Error ({type(e).__name__}): {e}")
        import traceback

        traceback.print_exc()
    finally:
        # C2: guard both so a failure creating the cursor doesn't raise
        # NameError here and mask the original error / leak the connection.
        if cursor:
            cursor.close()
        if connection:
            connection.close()
        print("\nDatabase connection closed")


if __name__ == "__main__":
    main()
