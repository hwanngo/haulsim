"""
Trip analysis, material scheduling, and Excel export — extracted from simulation_generator.py (behavior-preserving).
"""

import math
from typing import Dict, List, Optional, Tuple

try:
    from openpyxl import Workbook

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from backend.scripts.simgen.constants import *  # noqa: F401, F403

__all__ = [
    "OPENPYXL_AVAILABLE",
    "build_machine_id_to_hauler_group",
    "analyze_hauler_trips_from_telemetry",
    "create_material_schedule_from_trips",
    "create_material_schedule_data",
    "create_operations_structure",
    "export_route_excel",
]


def _resolve_item_material(
    lz_name, zone_material_map, default_material, default_density
):
    """Per-zone (material, density) for a schedule item, falling back to the default."""
    if zone_material_map and lz_name in zone_material_map:
        return zone_material_map[lz_name]
    return default_material, default_density


def build_machine_id_to_hauler_group(
    machines: Dict[int, Dict],
    machines_with_events: Optional[Dict] = None,
    model_name_to_machine_list_id: Optional[Dict] = None,
) -> Dict[int, int]:
    """
    Build a mapping from machine_id to 1-based hauler group id.

    Reproduces the exact rule used in create_model's hauler-build loop:
    - Iterate machines.items() in insertion order (NOT sorted).
    - Skip if machines_with_events is not None and machine_id not in it.
    - Skip if model_name_to_machine_list_id is not None and the machine's
      model_name (via extract_machine_model(type_name)) is not a key in it.
    - Otherwise assign an incrementing 1-based group id.

    Args:
        machines: Dict mapping machine_id -> machine_info dict (with "type_name").
        machines_with_events: Optional set/collection of machine_ids that have events.
            Pass None to skip the events filter.
        model_name_to_machine_list_id: Optional dict mapping model_name -> machine_list id.
            Pass None to skip the model-name filter.

    Returns:
        Dict mapping machine_id -> hauler group id (1-based, insertion-order).
    """
    from backend.scripts.simgen.loaders import extract_machine_model

    machine_id_to_hauler_group: Dict[int, int] = {}
    hauler_id = 1
    for machine_id, machine_info in machines.items():
        # Filter 1: machines with events
        if machines_with_events is not None and machine_id not in machines_with_events:
            continue
        # Filter 2: model name must be in the machine list
        if model_name_to_machine_list_id is not None:
            type_name = machine_info.get("type_name", "Unknown")
            model_name = extract_machine_model(type_name)
            if model_name_to_machine_list_id.get(model_name) is None:
                continue
        machine_id_to_hauler_group[machine_id] = hauler_id
        hauler_id += 1
    return machine_id_to_hauler_group


def analyze_hauler_trips_from_telemetry(
    telemetry_data: List[Tuple],
    load_zones: List[Dict],
    dump_zones: List[Dict],
    coordinates_in_meters: bool = False,
    payload_threshold: float = LOADED_PAYLOAD_THRESHOLD,
) -> Dict[int, List[Dict]]:
    """
    Analyze telemetry data to extract actual hauler trips (load zone -> dump zone).

    Detects complete cycles by tracking payload transitions:
    - LOAD: payload transitions from empty (<50%) to loaded (>50%)
    - DUMP: payload transitions from loaded (>50%) to empty (<50%)

    Args:
        telemetry_data: List of telemetry tuples
        load_zones: List of load zone dictionaries with detected_location
        dump_zones: List of dump zone dictionaries with detected_location
        coordinates_in_meters: If True, coordinates are in meters; otherwise millimeters
        payload_threshold: Payload percentage threshold (default 50%)

    Returns:
        Dictionary mapping machine_id -> list of trips
        Each trip: {"load_zone_id": int, "dump_zone_id": int, "load_zone_name": str, "dump_zone_name": str}
    """
    if not telemetry_data:
        return {}

    # Build zone lookups with locations
    def get_zone_location(zone):
        loc = zone.get("detected_location") or zone.get("settings", {}).get(
            "detected_location"
        )
        if loc:
            return loc.get("x", 0), loc.get("y", 0)
        return None

    lz_locations = []
    for z in load_zones:
        loc = get_zone_location(z)
        if loc:
            lz_locations.append(
                {
                    "id": z["id"],
                    "name": z.get("name", f"Load zone {z['id']}"),
                    "x": loc[0],
                    "y": loc[1],
                }
            )

    dz_locations = []
    for z in dump_zones:
        loc = get_zone_location(z)
        if loc:
            dz_locations.append(
                {
                    "id": z["id"],
                    "name": z.get("name", f"Dump zone {z['id']}"),
                    "x": loc[0],
                    "y": loc[1],
                }
            )

    def find_nearest_zone(x, y, zones):
        """Find nearest zone to (x, y) coordinates."""
        if not zones:
            return None
        best = None
        best_dist = float("inf")
        for z in zones:
            dx = x - z["x"]
            dy = y - z["y"]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < best_dist:
                best_dist = dist
                best = z
        return (
            best if best_dist < TRANSITION_TO_ZONE_MAX_DIST_M else None
        )  # Max 500m from zone center

    # Group telemetry by machine_id and sort by time
    # Tuple format: (machine_id[0], segment_id[1], cycle_id[2], interval[3],
    #                 pathEasting[4], pathNorthing[5], pathElevation[6], ...)
    machine_data = {}
    for row in telemetry_data:
        machine_id = row[0] if len(row) > 0 else None
        if machine_id is None:
            continue

        if machine_id not in machine_data:
            machine_data[machine_id] = []

        # Extract data: (timestamp, x, y, payload)
        timestamp = row[3] if len(row) > 3 else 0
        if coordinates_in_meters:
            x = float(row[4]) if len(row) > 4 and row[4] is not None else 0
            y = float(row[5]) if len(row) > 5 and row[5] is not None else 0
        else:
            x = row[4] / 1000.0 if len(row) > 4 and row[4] is not None else 0
            y = row[5] / 1000.0 if len(row) > 5 and row[5] is not None else 0
        payload = row[13] if len(row) > 13 and row[13] is not None else 0

        machine_data[machine_id].append(
            {
                "timestamp": timestamp,
                "x": x,
                "y": y,
                "payload": payload,
            }
        )

    # Analyze trips for each machine
    trips_by_machine = {}
    for machine_id, data_points in machine_data.items():
        # Sort by timestamp
        data_points.sort(key=lambda p: p["timestamp"])

        trips = []
        prev_loaded = None
        current_load_zone = None

        for point in data_points:
            payload = point["payload"]
            is_loaded = payload >= payload_threshold

            if prev_loaded is not None:
                # Detect LOAD transition (empty -> loaded)
                if not prev_loaded and is_loaded:
                    zone = find_nearest_zone(point["x"], point["y"], lz_locations)
                    if zone:
                        current_load_zone = zone

                # Detect DUMP transition (loaded -> empty)
                elif prev_loaded and not is_loaded:
                    zone = find_nearest_zone(point["x"], point["y"], dz_locations)
                    if zone and current_load_zone:
                        # Complete trip detected
                        trips.append(
                            {
                                "load_zone_id": current_load_zone["id"],
                                "load_zone_name": current_load_zone["name"],
                                "dump_zone_id": zone["id"],
                                "dump_zone_name": zone["name"],
                            }
                        )
                    current_load_zone = None

            prev_loaded = is_loaded

        if trips:
            trips_by_machine[machine_id] = trips

    return trips_by_machine


def create_material_schedule_from_trips(
    trips_by_machine: Dict[int, List[Dict]],
    routes: List[Dict] = None,
    haulers: List[Dict] = None,
    machine_id_to_hauler_group: Dict[int, int] = None,
    load_zones: List[Dict] = None,
    dump_zones: List[Dict] = None,
    default_density: float = DEFAULT_MATERIAL_DENSITY,
    default_material: str = "Ore",
    zone_material_map: Optional[Dict[str, Tuple[str, float]]] = None,
) -> List[Dict]:
    """
    Create material schedule data from analyzed hauler trips.

    Groups trips by (hauler_group_id, load_zone, dump_zone) based on actual
    GPS data. Matches routes by zone pair and validates that total num_of_hauler
    per hauler_group_id does not exceed the group's number_of_haulers capacity.

    Args:
        trips_by_machine: Dictionary from analyze_hauler_trips_from_telemetry
        routes: List of route dictionaries for route matching
        haulers: List of hauler dictionaries from model
        machine_id_to_hauler_group: Mapping of machine_id to hauler group_id
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        default_density: Default material density
        default_material: Default material name

    Returns:
        List of material schedule data items
    """
    if not trips_by_machine:
        return []

    # Fallback: if no mapping provided, each machine is its own group
    if not machine_id_to_hauler_group:
        all_machine_ids = sorted(trips_by_machine.keys())
        machine_id_to_hauler_group = {
            mid: idx for idx, mid in enumerate(all_machine_ids, start=1)
        }

    # Build hauler group capacity: group_id -> total number_of_haulers
    group_capacity = {}
    if haulers:
        for h in haulers:
            gid = h.get("group_id")
            if gid is not None:
                group_capacity[gid] = group_capacity.get(gid, 0) + h.get(
                    "number_of_haulers", 1
                )

    # Group trips by (hauler_group_id, load_zone_name, dump_zone_name)
    # and track unique machines per combination
    group_zone_machines = {}
    for machine_id, trips in trips_by_machine.items():
        group_id = machine_id_to_hauler_group.get(machine_id)
        if group_id is None:
            continue

        for trip in trips:
            lz_name = trip["load_zone_name"]
            dz_name = trip["dump_zone_name"]
            key = (group_id, lz_name, dz_name)
            if key not in group_zone_machines:
                group_zone_machines[key] = set()
            group_zone_machines[key].add(machine_id)

    # E-4: only emit schedule entries for (lz,dz) pairs that have a real route.
    # Routes were restricted to observed-trip pairs (sub-project B); an observed
    # pair with no connected path is dropped from routes. Without this filter the
    # schedule would reference a non-existent route (a dangling ref). When routes
    # is None (legacy caller), behave as before (no filtering).
    routable_pairs = None
    if routes:
        _lz_name = {z["id"]: z.get("name") for z in (load_zones or [])}
        _dz_name = {z["id"]: z.get("name") for z in (dump_zones or [])}
        routable_pairs = {
            (_lz_name.get(r.get("load_zone")), _dz_name.get(r.get("dump_zone")))
            for r in routes
        }

    # Build material schedule items with capacity validation
    material_data = []
    group_assigned = {}  # group_id -> total num_of_hauler assigned so far

    for group_id, lz_name, dz_name in sorted(group_zone_machines.keys()):
        unique_machines = group_zone_machines[(group_id, lz_name, dz_name)]
        num_haulers = len(unique_machines)

        # E-4: skip observed pairs that have no emitted route (would dangle).
        if routable_pairs is not None and (lz_name, dz_name) not in routable_pairs:
            print(
                f"    Schedule: skipping unroutable observed pair "
                f"({lz_name} -> {dz_name}) — no route emitted"
            )
            continue

        # Validate: total assigned for this group must not exceed capacity
        current_assigned = group_assigned.get(group_id, 0)
        max_capacity = group_capacity.get(group_id, num_haulers)
        remaining = max_capacity - current_assigned
        if remaining <= 0:
            continue
        num_haulers = min(num_haulers, remaining)

        group_assigned[group_id] = current_assigned + num_haulers

        _mat, _den = _resolve_item_material(
            lz_name, zone_material_map, default_material, default_density
        )
        item = {
            "id": len(material_data) + 1,
            "load_zone": lz_name,
            "dump_zone": dz_name,
            "route": "",
            "auto_generate_route": True,
            "material": _mat,
            "density": _den,
            "num_of_hauler": num_haulers,
            "assigned_machine_type": "Hauler",
            "multiple_routes": False,
            "hauler_group_id": group_id,
        }
        material_data.append(item)

    return material_data


def create_material_schedule_data(
    routes: List[Dict],
    load_zones: List[Dict],
    dump_zones: List[Dict],
    haulers: List[Dict] = None,
    telemetry_data: List[Tuple] = None,
    coordinates_in_meters: bool = False,
    machine_id_to_hauler_group: Dict[int, int] = None,
    default_density: float = DEFAULT_MATERIAL_DENSITY,
    default_material: str = "Ore",
    zone_material_map: Optional[Dict[str, Tuple[str, float]]] = None,
) -> List[Dict]:
    """
    Create material schedule data based on actual telemetry trips or routes.

    If telemetry_data is provided, analyzes actual hauler trips to determine
    which haulers traveled between which zones. Otherwise, falls back to
    generating items from routes.

    Args:
        routes: List of route dictionaries with load_zone and dump_zone references
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        haulers: Optional list of hauler dictionaries
        telemetry_data: Optional telemetry data for actual trip analysis
        coordinates_in_meters: Whether telemetry coordinates are in meters
        machine_id_to_hauler_group: Mapping of machine_id to hauler group_id
        default_density: Default material density in kg/m³
        default_material: Default material name

    Returns:
        List of material schedule data items
    """
    # Try to analyze actual trips from telemetry data first
    if telemetry_data and load_zones and dump_zones:
        trips_by_machine = analyze_hauler_trips_from_telemetry(
            telemetry_data, load_zones, dump_zones, coordinates_in_meters
        )
        if trips_by_machine:
            return create_material_schedule_from_trips(
                trips_by_machine,
                routes=routes,
                haulers=haulers,
                machine_id_to_hauler_group=machine_id_to_hauler_group,
                load_zones=load_zones,
                dump_zones=dump_zones,
                default_density=default_density,
                default_material=default_material,
                zone_material_map=zone_material_map,
            )

    # Fallback: generate from routes
    if not routes:
        return []

    # Build zone name lookups
    lz_lookup = {z["id"]: z.get("name", f"Load zone {z['id']}") for z in load_zones}
    dz_lookup = {z["id"]: z.get("name", f"Dump zone {z['id']}") for z in dump_zones}

    # Build hauler group capacity: group_id -> total number_of_haulers
    group_capacity = {}
    if haulers:
        for h in haulers:
            gid = h.get("group_id")
            if gid is not None:
                group_capacity[gid] = group_capacity.get(gid, 0) + h.get(
                    "number_of_haulers", 1
                )

    sorted_groups = sorted(group_capacity.keys()) if group_capacity else []
    group_assigned = {}  # group_id -> total assigned so far

    material_data = []
    for route in routes:
        lz_id = route.get("load_zone")
        dz_id = route.get("dump_zone")

        lz_name = lz_lookup.get(lz_id, f"Load zone {lz_id}")
        dz_name = dz_lookup.get(dz_id, f"Dump zone {dz_id}")

        # Find a hauler group with remaining capacity
        assigned_group = None
        num_haulers = 1
        for gid in sorted_groups:
            capacity = group_capacity.get(gid, 0)
            used = group_assigned.get(gid, 0)
            remaining = capacity - used
            if remaining > 0:
                assigned_group = gid
                num_haulers = 1
                group_assigned[gid] = used + num_haulers
                break

        if assigned_group is None:
            # No hauler capacity left, skip this route
            continue

        _mat, _den = _resolve_item_material(
            lz_name, zone_material_map, default_material, default_density
        )
        item = {
            "id": len(material_data) + 1,
            "load_zone": lz_name,
            "dump_zone": dz_name,
            "route": "",
            "auto_generate_route": True,
            "material": _mat,
            "density": _den,
            "num_of_hauler": num_haulers,
            "assigned_machine_type": "Hauler",
            "multiple_routes": False,
            "hauler_group_id": assigned_group,
        }
        material_data.append(item)

    return material_data


def create_operations_structure(
    routes: List[Dict],
    load_zones: List[Dict],
    dump_zones: List[Dict],
    haulers: List[Dict] = None,
    telemetry_data: List[Tuple] = None,
    coordinates_in_meters: bool = False,
    machine_id_to_hauler_group: Dict[int, int] = None,
    schedule_name: str = "Material Schedule 1",
    scheduling_method: str = "grouped_assignment",
    material: str = DEFAULT_MATERIAL,
    density: float = DEFAULT_MATERIAL_DENSITY,
    zone_material_map: Optional[Dict[str, Tuple[str, float]]] = None,
) -> Dict:
    """
    Create the complete operations structure with material schedules.

    Args:
        routes: List of route dictionaries
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        haulers: Optional list of hauler dictionaries
        telemetry_data: Optional telemetry data for actual trip analysis
        coordinates_in_meters: Whether telemetry coordinates are in meters
        machine_id_to_hauler_group: Mapping of machine_id to hauler group_id
        schedule_name: Name for the material schedule
        scheduling_method: Scheduling method (grouped_assignment, production_target_based, etc.)

    Returns:
        Operations dictionary with material_schedules structure
    """
    material_data = create_material_schedule_data(
        routes,
        load_zones,
        dump_zones,
        haulers,
        telemetry_data=telemetry_data,
        coordinates_in_meters=coordinates_in_meters,
        machine_id_to_hauler_group=machine_id_to_hauler_group,
        default_material=material,
        default_density=density,
        zone_material_map=zone_material_map,
    )

    return {
        "material_schedules": {
            "selected_material": 1,
            "all_material_schedule": [
                {
                    "id": 1,
                    "name": schedule_name,
                    "hauler_assignment": {"scheduling_method": scheduling_method},
                    "mixed_fleet_based_initial_assignment": False,
                    "data": material_data,
                }
            ],
        },
        "operational_delays": {
            "haulers": [],
            "trolleys": [],
            "load_zones": [],
            "dump_zones": [],
        },
    }


def export_route_excel(
    nodes: List[Dict],
    roads: List[Dict],
    load_zones: List[Dict],
    dump_zones: List[Dict],
    routes: List[Dict],
    output_path: str,
) -> Optional[str]:
    """
    Export route data to Excel file following Route_Template format.

    The Route_Data sheet contains node coordinates for each route with
    the following columns:
    - Easting (m): X coordinate
    - Northing (m): Y coordinate
    - Elevation (m): Z coordinate
    - RouteIndex: Route identifier (road_id)
    - Segment: "haul" or "return"
    - Load Zone: Load zone name
    - Dump Zone: Dump zone name
    - Rolling Resistance (%): Optional
    - Speed Limit (kph): Optional
    - Trolley: Optional
    - Banking (%): Optional
    - Curvature (1/m): Optional
    - Lane Width (m): Optional
    - Traction Coefficient: Optional

    Args:
        nodes: List of node dictionaries with coords
        roads: List of road dictionaries with node IDs
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        routes: List of route dictionaries connecting zones
        output_path: Output file path for Excel file

    Returns:
        Path to generated Excel file, or None if openpyxl not available
    """
    if not OPENPYXL_AVAILABLE:
        print("    Warning: openpyxl not available, skipping Excel export")
        return None

    if not nodes or not roads:
        print("    Warning: No nodes or roads to export")
        return None

    # Build node lookup
    node_lookup = {n["id"]: n for n in nodes}

    # Build zone name lookups
    load_zone_lookup = {
        z["id"]: z.get("name", f"Load zone {z['id']}") for z in (load_zones or [])
    }
    dump_zone_lookup = {
        z["id"]: z.get("name", f"Dump zone {z['id']}") for z in (dump_zones or [])
    }

    # Build road lookup
    road_lookup = {r["id"]: r for r in roads}

    # Prepare data rows
    rows = []

    if routes:
        # Export based on routes (with Load Zone / Dump Zone info)
        for route in routes:
            route_id = route["id"]
            load_zone_id = route.get("load_zone")
            dump_zone_id = route.get("dump_zone")
            load_zone_name = load_zone_lookup.get(load_zone_id, "")
            dump_zone_name = dump_zone_lookup.get(dump_zone_id, "")

            # Export haul roads
            haul_road_ids = route.get("haul", [])
            for road_id in haul_road_ids:
                road = road_lookup.get(road_id)
                if not road:
                    continue
                for node_id in road.get("nodes", []):
                    node = node_lookup.get(node_id)
                    if not node:
                        continue
                    coords = node.get("coords", [0, 0, 0])
                    rows.append(
                        {
                            "Easting (m)": round(coords[0], 3),
                            "Northing (m)": round(coords[1], 3),
                            "Elevation (m)": round(coords[2], 3),
                            "RouteIndex": route_id,
                            "Segment": "haul",
                            "Load Zone": load_zone_name,
                            "Dump Zone": dump_zone_name,
                            "Rolling Resistance (%)": node.get(
                                "rolling_resistance", ""
                            ),
                            "Speed Limit (kph)": node.get("speed_limit", ""),
                            "Trolley": "",
                            "Banking (%)": node.get("banking", ""),
                            "Curvature (1/m)": node.get("curvature", ""),
                            "Lane Width (m)": node.get("lane_width", ""),
                            "Traction Coefficient": node.get("traction", ""),
                        }
                    )

            # Export return roads
            return_road_ids = route.get("return", [])
            for road_id in return_road_ids:
                road = road_lookup.get(road_id)
                if not road:
                    continue
                for node_id in road.get("nodes", []):
                    node = node_lookup.get(node_id)
                    if not node:
                        continue
                    coords = node.get("coords", [0, 0, 0])
                    rows.append(
                        {
                            "Easting (m)": round(coords[0], 3),
                            "Northing (m)": round(coords[1], 3),
                            "Elevation (m)": round(coords[2], 3),
                            "RouteIndex": route_id,
                            "Segment": "return",
                            "Load Zone": load_zone_name,
                            "Dump Zone": dump_zone_name,
                            "Rolling Resistance (%)": node.get(
                                "rolling_resistance", ""
                            ),
                            "Speed Limit (kph)": node.get("speed_limit", ""),
                            "Trolley": "",
                            "Banking (%)": node.get("banking", ""),
                            "Curvature (1/m)": node.get("curvature", ""),
                            "Lane Width (m)": node.get("lane_width", ""),
                            "Traction Coefficient": node.get("traction", ""),
                        }
                    )
    else:
        # Fallback: Export roads without route info (Segment = "road")
        for road in roads:
            road_id = road["id"]
            for node_id in road.get("nodes", []):
                node = node_lookup.get(node_id)
                if not node:
                    continue
                coords = node.get("coords", [0, 0, 0])
                rows.append(
                    {
                        "Easting (m)": round(coords[0], 3),
                        "Northing (m)": round(coords[1], 3),
                        "Elevation (m)": round(coords[2], 3),
                        "RouteIndex": road_id,
                        "Segment": "road",
                        "Load Zone": "",
                        "Dump Zone": "",
                        "Rolling Resistance (%)": node.get("rolling_resistance", ""),
                        "Speed Limit (kph)": node.get("speed_limit", ""),
                        "Trolley": "",
                        "Banking (%)": node.get("banking", ""),
                        "Curvature (1/m)": node.get("curvature", ""),
                        "Lane Width (m)": node.get("lane_width", ""),
                        "Traction Coefficient": node.get("traction", ""),
                    }
                )

    if not rows:
        print("    Warning: No route data to export")
        return None

    # Create DataFrame with column order matching template
    columns = [
        "Easting (m)",
        "Northing (m)",
        "Elevation (m)",
        "RouteIndex",
        "Segment",
        "Rolling Resistance (%)",
        "Speed Limit (kph)",
        "Load Zone",
        "Dump Zone",
        "Trolley",
        "Banking (%)",
        "Curvature (1/m)",
        "Lane Width (m)",
        "Traction Coefficient",
    ]
    # Write to Excel with a Route_Data sheet (openpyxl directly; empty strings -> blank cells)
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Route_Data"
        ws.append(columns)
        for r in rows:
            ws.append([(r.get(c) if r.get(c) != "" else None) for c in columns])
        wb.save(output_path)
        return output_path
    except (OSError, ValueError) as e:
        # OSError: disk/permission; ValueError: bad sheet/cell args.
        # Anything else is unexpected -> propagate.
        print(f"    Error writing Excel file ({type(e).__name__}): {e}")
        return None
