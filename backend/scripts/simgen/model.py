"""
Hauler/loader model building — extracted from simulation_generator.py (behavior-preserving).
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.scripts.simgen.constants import *  # noqa: F401, F403
from backend.scripts.simgen.roads import find_connected_components
from backend.scripts.simgen.routes import create_routes, update_zone_settings_for_routes
from backend.scripts.simgen.operations import (
    create_operations_structure,
    build_machine_id_to_hauler_group,
    analyze_hauler_trips_from_telemetry,
)

__all__ = [
    "find_center_nodes_for_haulers",
    "create_service_stations_for_haulers",
    "create_model",
]


def find_center_nodes_for_haulers(
    nodes: List[Dict],
    roads: List[Dict],
    machine_first_positions: Dict[int, Tuple[float, float, float]],
) -> Dict[int, int]:
    """
    Find center node for each hauler based on connected components.
    Haulers in the same network component share the same center node.

    Args:
        nodes: List of node dictionaries
        roads: List of road dictionaries
        machine_first_positions: Dict mapping machine_id to (x, y, z) coordinates

    Returns:
        Dict mapping machine_id to center_node_id
    """
    if not nodes or not roads or not machine_first_positions:
        return {}

    # Find connected components
    components = find_connected_components(roads)
    if not components:
        return {}

    # Build node_id -> coords lookup
    node_coords = {n["id"]: (n["coords"][0], n["coords"][1]) for n in nodes}

    def find_nearest_node_in_set(
        x: float, y: float, node_set: Set[int]
    ) -> Optional[int]:
        """Find nearest node to (x, y) within a specific node set."""
        min_dist = float("inf")
        nearest = None
        # Sorted iteration: deterministic tie-break when nodes are equidistant
        # (node_set is a set; its iteration order is not stable run-to-run).
        for nid in sorted(node_set):
            if nid not in node_coords:
                continue
            nx, ny = node_coords[nid]
            dist = (x - nx) ** 2 + (y - ny) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest = nid
        return nearest

    # Group haulers by component
    component_haulers = defaultdict(
        list
    )  # component_idx -> [(machine_id, nearest_node_id)]

    for machine_id, (x, y, z) in machine_first_positions.items():
        nearest_node = None
        component_idx = None
        min_dist = float("inf")

        # Find which component this hauler belongs to
        for idx, component in enumerate(components):
            node_id = find_nearest_node_in_set(x, y, component)
            if node_id:
                nx, ny = node_coords[node_id]
                dist = (x - nx) ** 2 + (y - ny) ** 2
                if dist < min_dist:
                    min_dist = dist
                    nearest_node = node_id
                    component_idx = idx

        if component_idx is not None:
            component_haulers[component_idx].append((machine_id, nearest_node))

    # Find center node for each component that has haulers
    def find_component_center(
        component: Set[int], hauler_nodes: List[int]
    ) -> Optional[int]:
        """Find node in component closest to centroid of hauler positions."""
        hauler_coords_list = [
            node_coords[nid] for nid in hauler_nodes if nid in node_coords
        ]
        if not hauler_coords_list:
            return None

        # Calculate centroid of hauler positions
        center_x = sum(c[0] for c in hauler_coords_list) / len(hauler_coords_list)
        center_y = sum(c[1] for c in hauler_coords_list) / len(hauler_coords_list)

        # Find actual node in component closest to centroid
        min_dist = float("inf")
        center_node = None
        for nid in component:
            if nid not in node_coords:
                continue
            nx, ny = node_coords[nid]
            dist = (center_x - nx) ** 2 + (center_y - ny) ** 2
            if dist < min_dist:
                min_dist = dist
                center_node = nid

        return center_node

    # Build result: machine_id -> center_node_id
    result = {}
    for comp_idx, haulers in component_haulers.items():
        component = components[comp_idx]
        hauler_nodes = [node_id for _, node_id in haulers]
        center_node = find_component_center(component, hauler_nodes)

        for machine_id, _ in haulers:
            result[machine_id] = center_node

    return result


def create_service_stations_for_haulers(
    center_nodes: Dict[int, int],
    nodes: List[Dict],
    roads: List[Dict],
) -> Tuple[List[Dict], List[Dict], Dict[int, Tuple[int, int]]]:
    """
    Create service stations and fuel zones at center nodes for hauler initial positions.

    Args:
        center_nodes: Dict mapping machine_id to center_node_id
        nodes: List of node dictionaries
        roads: List of road dictionaries

    Returns:
        Tuple of:
        - List of service station dictionaries
        - List of charger (fuel zone) dictionaries
        - Dict mapping machine_id to (service_zone_id, service_zone_spot_id)
    """
    if not center_nodes:
        return [], [], {}

    # Get unique center nodes
    unique_centers = set(center_nodes.values())
    node_coords = {n["id"]: n["coords"] for n in nodes}

    # Build node_to_roads mapping
    node_to_roads = defaultdict(list)
    for road in roads:
        for nid in road.get("nodes", []):
            node_to_roads[nid].append(road["id"])

    service_stations = []
    chargers = []
    node_to_service = {}  # center_node_id -> service_zone_id

    for idx, center_node_id in enumerate(sorted(unique_centers), start=1):
        if center_node_id is None:
            continue

        node_coords.get(center_node_id, [0, 0, 0])
        road_ids = node_to_roads.get(center_node_id, [])

        # Use first road for in/out if available
        inroad_ids = [road_ids[0]] if road_ids else []
        outroad_ids = [road_ids[0]] if road_ids else []

        # Create service station
        service_station = {
            "id": idx,
            "name": f"Service {idx}",
            "is_generated": True,
            "is_deactive": False,
            "is_show_service": True,
            "settings": {
                "n_spots": 2,  # Always 2 spots per service station
                "roadlength": 100,
                "speed_limit": "",
                "rolling_resistance": "",
                "flip": False,
                "dtheta": 0,
                "n_entrances": 1,
                "queing": False,
                "reverse_speed_limit": "",
                "width": 50,
                "angular_spread": 80,
                "create_uturn_road": False,
                "clearance_radius": 80,
                "access_distance": 40,
                "zonetype": "servicestandard",
                "inroad_ids": inroad_ids,
                "outroad_ids": outroad_ids,
                "innode_ids": [center_node_id],
                "outnode_ids": [center_node_id],
            },
        }
        service_stations.append(service_station)

        # Create charger (fuel zone) at same location
        charger = {
            "id": idx,
            "name": f"Fuel Zone {idx}",
            "type": "diesel",
            "output_power": "",
            "connect_time": "",
            "disconnect_time": "",
            "efficiency": "",
            "ramup_time": "",
            "cable_efficiency": "",
            "is_generated": True,
            "is_deactive": False,
            "power_factor": "",
            "power_factor_lagging": "",
            "fuel_rate": "",
            "settings": {
                "n_spots": 6,
                "roadlength": 100,
                "speed_limit": "",
                "rolling_resistance": "",
                "flip": False,
                "dtheta": 0,
                "n_entrances": 1,
                "queing": False,
                "reverse_speed_limit": "",
                "width": 50,
                "angular_spread": 80,
                "create_uturn_road": False,
                "clearance_radius": 80,
                "access_distance": 40,
                "zonetype": "amtinspectionbays",
                "additional_battery": 0,
                "inroad_ids": inroad_ids,
                "outroad_ids": outroad_ids,
                "innode_ids": [center_node_id],
                "outnode_ids": [center_node_id],
            },
        }
        chargers.append(charger)

        node_to_service[center_node_id] = idx

    # Build machine_id -> (service_zone_id, spot_id) mapping
    # Distribute haulers evenly between spot 1 and spot 2
    service_spot_counters = defaultdict(
        int
    )  # service_id -> current count (for alternating)
    hauler_to_service = {}

    for machine_id, center_node_id in center_nodes.items():
        if center_node_id is None:
            continue
        service_id = node_to_service.get(center_node_id)
        if service_id:
            # Alternate between spot 1 and 2
            service_spot_counters[service_id] += 1
            spot_id = 1 if service_spot_counters[service_id] % 2 == 1 else 2
            hauler_to_service[machine_id] = (service_id, spot_id)

    return service_stations, chargers, hauler_to_service


def create_model(
    nodes: List[Dict],
    roads: List[Dict],
    load_zones: List[Dict] = None,
    dump_zones: List[Dict] = None,
    version: str = "2.0.51",
    machines: Optional[Dict[int, Dict]] = None,
    machines_list: Optional[Dict[str, Any]] = None,
    machines_with_events: Optional[Set[int]] = None,
    telemetry_data: Optional[List[Tuple]] = None,
    coordinates_in_meters: bool = False,
    material: str = DEFAULT_MATERIAL,
    density: float = DEFAULT_MATERIAL_DENSITY,
    zone_material_map: Optional[Dict[str, Tuple[str, float]]] = None,
) -> Dict:
    """
    Create complete model structure with full settings.

    Args:
        nodes: List of node dictionaries
        roads: List of road dictionaries
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        version: Model version string
        machines: Machine info dictionary (from database or import)
        machines_list: Machine specifications by model name (from machines.json)
        machines_with_events: Set of machine IDs that have events data
        telemetry_data: Raw telemetry data for determining hauler initial positions
        coordinates_in_meters: Whether telemetry coordinates are in meters (True) or mm (False)

    Returns:
        Complete model dictionary
    """
    from backend.scripts.simgen.loaders import (
        extract_machine_model,
        get_machine_spec_from_list,
        deep_copy_dict,
    )

    load_zones = load_zones or []
    dump_zones = dump_zones or []

    # Build machine_list from machines using machines.json data
    machine_list_haulers = []
    machine_list_loaders = []
    added_model_names = set()  # Track added models to avoid duplicates
    model_name_to_machine_list_id = {}  # Map model_name -> machine_list hauler id

    if machines and machines_list:
        for machine_id, machine_info in machines.items():
            # Skip machines without events if filter is provided
            if (
                machines_with_events is not None
                and machine_id not in machines_with_events
            ):
                continue

            type_name = machine_info.get("type_name", "Unknown")
            model_name = extract_machine_model(type_name)

            if model_name and model_name not in added_model_names:
                # Get spec from machines.json
                spec_data = get_machine_spec_from_list(type_name, machines_list)
                if spec_data:
                    hauler_data = deep_copy_dict(spec_data)
                    hauler_data["model_name"] = type_name
                    machine_list_haulers.append(hauler_data)
                    # Track mapping from model_name to machine_list hauler id
                    model_name_to_machine_list_id[model_name] = hauler_data.get(
                        "id", len(machine_list_haulers)
                    )
                    added_model_names.add(model_name)

    # Add default loader from machines.json (first loader available)
    default_loader_machine_list_id = None
    if machines_list:
        loaders_in_list = machines_list.get("machine_list", {}).get("loaders", [])
        if loaders_in_list:
            default_loader = deep_copy_dict(loaders_in_list[0])
            machine_list_loaders.append(default_loader)
            default_loader_machine_list_id = default_loader.get("id", 1)

    # Compute observed load/dump pairs from telemetry (None = geometric/all-pairs mode)
    if telemetry_data:
        trips = analyze_hauler_trips_from_telemetry(
            telemetry_data, load_zones, dump_zones, coordinates_in_meters
        )
        observed_pairs = {
            (t["load_zone_id"], t["dump_zone_id"]) for ts in trips.values() for t in ts
        }
        if not observed_pairs:
            print(
                "    Warning: telemetry present but no hauler trips detected — emitting zero observed-trip routes"
            )
    else:
        observed_pairs = None

    # Create routes and update zone settings to ensure connectivity
    routes = create_routes(
        load_zones, dump_zones, roads, nodes, observed_pairs=observed_pairs
    )
    update_zone_settings_for_routes(routes, load_zones, dump_zones, roads)

    # Discrepancy summary
    if observed_pairs is not None:
        observed_lz_ids = {p[0] for p in observed_pairs}
        observed_dz_ids = {p[1] for p in observed_pairs}
        zero_trip_lz = sum(1 for lz in load_zones if lz["id"] not in observed_lz_ids)
        zero_trip_dz = sum(1 for dz in dump_zones if dz["id"] not in observed_dz_ids)
        zero_trip_zone_count = zero_trip_lz + zero_trip_dz
    else:
        zero_trip_zone_count = 0
    print(
        f"    Routes: {len(load_zones)} load x {len(dump_zones)} dump zones, {len(observed_pairs) if observed_pairs is not None else 'N/A'} observed pairs, {len(routes)} routes emitted, {zero_trip_zone_count} zero-trip zones"
    )

    model = {
        "version": version,
        "machine_list": {
            "haulers": machine_list_haulers,
            "loaders": machine_list_loaders,
        },
        "map_id": -1,
        "map_translate": {
            "total_northing": 0,
            "total_easting": 0,
            "total_elevation": 0,
            "total_angle": 0,
        },
        "parameters": [],
        "nodes": nodes,
        "settings": {
            "ambient_temperature": 34,
            "intersection_dispatching": False,
            "reassignment_threshold_min": 5,
            "passing_bay_logic": False,
            "passing_bay_waiting_time": 0.75,
            "battery_state_of_health": 0.9,
            "fuel_when_to_fill_lvl": 0.1,
            "battery_min_pct": 0.1,
            "battery_max_pct": 0.9,
            "battery_trolley_pct": 0.9,
            "max_SOC_logic_for_DET": True,
            "det_rms_power": "off",
            "power_loss_model": False,
            "rail_resist_multiplier": 1,
            "battery_charge_pct": 0.9,
            "max_SOC_logic_for_SET": True,
            "driving_side": 0,
            "gap_between_lanes": 1.4,
            "road_merging_intersection": 0,
            "automatic_intersection_creation": True,
            "road_ways_num": 2,
            "road_lanes_num": 1,
            # Haul-road defaults grounded in published norms (reference_data/haul_road_design.json):
            # max mine flat speed ~50-60 km/h, well-maintained rolling resistance ~2%,
            # dry earth/rock traction ~0.6.
            "road_speed_limit": 60,
            "road_rolling_resistance": 2,
            "lane_width": 14.525,
            "road_traction_coefficient": 0.6,
            "banking": 0,
            "distance_between_lanes": 15.925,
            "reduce_speed_logic": True,
            "min_foll_dist": 50,
            "bump_prevention": True,
            "intersection_system": "simple",
            "des_inputs_settings": {
                "curvature_based": False,
                "curvature_speed_application": True,
                "cfh_version": 13,
                "super_elevation": "flat_curve",
                "max_distance_curve_radius": 50,
                "driver_speed_behavior": False,
                "dsb_distance": 500,
                "dsb_threshold": 20,
                "grade_limits": False,
                "interpolate_speed_limit": False,
                # Speed limits (km/h) and grade band edges (%) align with mining haul-road
                # norms: loaded flat ~40-50, empty flat ~50-60, loaded downgrade brake-limited.
                # "steep" bands start at the ~10% sustained design max (was 15%); see
                # reference_data/haul_road_design.json.
                "loaded_flat_speed_limits": 40,
                "empty_flat_speed_limits": 60,
                "loaded_steep_downhill_grades": -10,
                "empty_steep_downhill_grades": -10,
                "loaded_steep_downhill_speed_limits": 10,
                "empty_steep_downhill_speed_limits": 15,
                "loaded_downhill_grades": -5,
                "empty_downhill_grades": -5,
                "loaded_downhill_speed_limits": 20,
                "empty_downhill_speed_limits": 30,
                "loaded_uphill_grades": 5,
                "empty_uphill_grades": 5,
                "loaded_uphill_speed_limits": 30,
                "empty_uphill_speed_limits": 45,
                "loaded_steep_uphill_grades": 10,
                "empty_steep_uphill_grades": 10,
                "loaded_steep_uphill_speed_limits": 20,
                "empty_steep_uphill_speed_limits": 30,
                "lane_width": 10,
                "driving_side": 0,
                "gap_between_lanes": 1.4,
                "road_network_logic": False,
                "require_energy_zone": True,
                "max_SOC_logic_for_SET": True,
                "max_SOC_logic_for_DET": True,
                "road_merging_intersection": 0,
                "reassignment_threshold_min": 5,
                "road_traction_coefficient": 0.6,
                "bump_prevention": True,
                "create_intersection_object": False,
                "automatic_intersection_creation": True,
                "intersection_dispatching": False,
                "det_rms_power": "off",
                "banking": 0,
                "corner_speed_limit": False,
            },
            "target_payload": 100,
            "variation_model": -1,
            "loader_time_variation": 0,
            "loader_payload_variation": 0,
            "truck_time_variation": 0,
            "truck_payload_variation": 0,
            "payload_precision": 0.05,
            "tires": {
                "calculate_TKPH": False,
                "TKPH_RollingWindow": 60,
                "TKPH_ambient_temperature": 34,
                "TKPH_speed_adjustment": False,
                "front_tire_TKPH_limit": 1394,
                "rear_tire_TKPH_limit": 1394,
                "front_tire_TKPH_deactivate_limit": 1000,
                "rear_tire_TKPH_deactivate_limit": 1000,
                "TKPH_limiting_speed": 25,
            },
            "fueling_charging_dispatching": {
                "prerun_soc_buffer": 0.05,
                "prerun_soc_buffer_trolley": 0.05,
                "soe_penalty": 1,
                "charging_strategy": "rule_based",
                "fueling_charging_dispatching_policy": "when_empty",
            },
            "create_intersection_object": False,
            "new_prerun": False,
            "new_fpc": True,
            "sim_time": 240,
            "random_seed": 1234,
            "material_density": 1700,
            "operational_delays": "off",
            "require_energy_zone": True,
            "road_network_logic": True,
            "intersections": {
                "intersect_logic": True,
                "intersect_length": 0,
                "intersect_yield": True,
                "intersect_yield_distance": 100,
                "intersect_yield_speed": 10,
            },
            "curvature_speed_application": True,
            "power_averaging_and_derate": False,
            "secondary_check_for_CZ_dispatch": True,
        },
        "default_powernode_priorities": {
            "loaders": 0,
            "crushers": 0,
            "trolleys": 2,
            "chargers": 4,
        },
        "economic_settings": {},
        "zone_defaults": {
            "trolley": {
                "type": "DET",
                "stop_propel": True,
                "queue_at_entry": False,
                "speed_reduction": False,
                "adaptive_speed_reduction_soc_target": 0.7,
                "connect_speed": 20,
                "maximum_speed": 45,
                "line_rail_efficiency": 0.95,
                "rejection_rate": 0,
                "substation_output_power_limit": 12000,
                "power_module_rms_limit": 9000,
                "substation_efficiency": 0.965,
                "rms_moving_time_window": 30,
                "power_factor": 0.9,
                "power_factor_lagging": "Lagging (Inductive)",
                "max_propel_preferred": False,
                "extra_buffer_demand_strategy": 1,
                "power_prioritization": 0,
                "trolley_length": 1,
                "battery_charge_pct": 0.9,
                "max_SOC_logic_for_DET": True,
            },
            "fuel_charge": {
                "connect_time": 3,
                "disconnect_time": 2,
                "ramup_time": 0.8,
                "output_power": 4000,
                "efficiency": 0.945,
                "cable_efficiency": 0.98,
                "power_factor": 0.9,
                "power_factor_lagging": "Lagging (Inductive)",
                "fuel_rate": 500,
                "fuel_connect_time": 3,
                "fuel_disconnect_time": 2,
                "auto_generate": {
                    "speed_limit": 20,
                    "rolling_resistance": 2,
                },
                "fuel_auto_generate": {
                    "speed_limit": 20,
                    "rolling_resistance": 2,
                },
            },
            "load": {
                "auto_generate": {
                    "speed_limit": 20,
                    "rolling_resistance": 2,
                    "reverse_speed_limit": 5,
                },
            },
            "dump": {
                "auto_generate": {
                    "speed_limit": 20,
                    "rolling_resistance": 2,
                    "reverse_speed_limit": 5,
                    "power_factor": 1,
                },
            },
            "service": {
                "auto_generate": {
                    "speed_limit": 20,
                    "rolling_resistance": 2,
                },
            },
        },
        "roads": roads,
        "trolleys": [],
        "chargers": [],
        "service_stations": [],
        "dump_zones": dump_zones,
        "load_zones": load_zones,
        "routes": routes,
        "haulers": [],
        "loaders": [],
        "simulates": [],
        "esses": [],
        "batteries": [],
        "crushers": [],
        "operations": create_operations_structure(
            routes,
            load_zones,
            dump_zones,
            telemetry_data=telemetry_data,
            coordinates_in_meters=coordinates_in_meters,
            schedule_name="Material Schedule 1",
            scheduling_method="grouped_assignment",
            material=material,
            density=density,
            zone_material_map=zone_material_map,
        ),
        "cameraPosition": {"x": 0, "y": 1000, "z": 0},
        "controlTarget": {"x": 0, "y": 0, "z": 0},
    }

    # Build haulers list from machines
    model_haulers = []
    if machines and model_name_to_machine_list_id:
        routes = model.get("routes", [])
        first_route_id = routes[0]["id"] if routes else None

        # Build lookup structures for determining initial positions
        {n["id"]: n for n in nodes}
        {r["id"]: r for r in roads}

        # Build mapping: node_id -> list of road_ids that contain this node
        node_to_roads = {}
        for road in roads:
            for nid in road.get("nodes", []):
                if nid not in node_to_roads:
                    node_to_roads[nid] = []
                node_to_roads[nid].append(road["id"])

        # Build mapping: road_id -> list of route_ids that use this road
        road_to_routes = {}
        for route in routes:
            for rid in route.get("haul", []) + route.get("return", []):
                if rid not in road_to_routes:
                    road_to_routes[rid] = []
                road_to_routes[rid].append(route["id"])

        # Group telemetry by machine_id to find first position
        machine_first_positions = {}
        if telemetry_data:
            for row in telemetry_data:
                mid = row[0]
                if mid not in machine_first_positions:
                    # First telemetry point for this machine
                    # row[4]=pathEasting, row[5]=pathNorthing, row[6]=pathElevation
                    if coordinates_in_meters:
                        x, y, z = row[4], row[5], row[6]
                    else:
                        x = row[4] / 1000.0
                        y = row[5] / 1000.0
                        z = row[6] / 1000.0
                    machine_first_positions[mid] = (x, y, z)

        # Find center nodes for each hauler based on connected road components
        # Filter positions to only include machines that will be processed
        filtered_positions = {}
        for machine_id, machine_info in machines.items():
            if (
                machines_with_events is not None
                and machine_id not in machines_with_events
            ):
                continue
            type_name = machine_info.get("type_name", "Unknown")
            model_name = extract_machine_model(type_name)
            if model_name_to_machine_list_id.get(model_name) is not None:
                if machine_id in machine_first_positions:
                    filtered_positions[machine_id] = machine_first_positions[machine_id]

        # Find center nodes and create service stations and fuel zones
        center_nodes = find_center_nodes_for_haulers(nodes, roads, filtered_positions)
        service_stations, chargers, hauler_to_service = (
            create_service_stations_for_haulers(center_nodes, nodes, roads)
        )

        # Add service stations and chargers to model
        model["service_stations"] = service_stations
        model["chargers"] = chargers

        # Build the machine_id -> group_id mapping via the shared helper (single source of truth).
        # This reproduces the exact same filter + ordering as the loop below.
        machine_id_to_hauler_group = build_machine_id_to_hauler_group(
            machines,
            machines_with_events=machines_with_events,
            model_name_to_machine_list_id=model_name_to_machine_list_id,
        )

        for machine_id, machine_info in machines.items():
            # Skip machines without events if filter is provided
            if (
                machines_with_events is not None
                and machine_id not in machines_with_events
            ):
                continue

            type_name = machine_info.get("type_name", "Unknown")
            model_name = extract_machine_model(type_name)

            # Get machine_list hauler id for this model
            machine_list_id = model_name_to_machine_list_id.get(model_name)
            if machine_list_id is None:
                continue

            # Group id comes from the shared helper mapping (same value as before)
            hauler_id = machine_id_to_hauler_group[machine_id]

            # Get service zone assignment for this hauler
            service_info = hauler_to_service.get(machine_id)

            # Get machine spec to determine type
            spec_data = (
                get_machine_spec_from_list(type_name, machines_list)
                if machines_list
                else None
            )
            machine_type = spec_data.get("type", "diesel") if spec_data else "diesel"
            is_electric = machine_type == "electric"

            # Use initial_position = 2 (service zone) if service zone is assigned
            if service_info:
                service_zone_id, service_zone_spot_id = service_info
                hauler = {
                    "id": hauler_id,
                    "group_id": hauler_id,
                    "key": "haulers",
                    "name": f"Hauler {hauler_id}",
                    "machine_id": machine_list_id,
                    "is_local_machine": None,
                    "geometry_name": "_default",
                    "model_scale": 1,
                    "type": machine_type,
                    "number_of_haulers": 1,
                    "lane": 2,
                    "initial_position": 2,  # 2 = service zone
                    "initial_level_pct": {"type": "exact", "value": 95},
                    "initial_conditions": {
                        "route_id": None,
                        "road_id": None,
                        "node_id": None,
                        "service_zone_id": service_zone_id,
                        "service_zone_spot_id": service_zone_spot_id,
                        "load_zone_id": None,
                        "assigned_load_spots": [],
                    },
                    "is_deactive": False,
                }
            else:
                # Fallback to route-based initial position
                hauler = {
                    "id": hauler_id,
                    "group_id": hauler_id,
                    "key": "haulers",
                    "name": f"Hauler {hauler_id}",
                    "machine_id": machine_list_id,
                    "is_local_machine": None,
                    "geometry_name": "_default",
                    "model_scale": 1,
                    "type": machine_type,
                    "number_of_haulers": 1,
                    "lane": 2,
                    "initial_position": 1,  # 1 = on route
                    "initial_level_pct": {"type": "exact", "value": 95},
                    "initial_conditions": {
                        "route_id": first_route_id,
                        "road_id": None,
                        "node_id": None,
                        "service_zone_id": None,
                        "service_zone_spot_id": None,
                        "load_zone_id": None,
                        "assigned_load_spots": [],
                    },
                    "is_deactive": False,
                }

            # Add type-specific fields
            if is_electric:
                hauler["battery_state_of_health"] = 90
                hauler["battery_capacity"] = (
                    spec_data.get("battery_size", 500) if spec_data else 500
                )
            else:
                hauler["fuel_tank"] = (
                    spec_data.get("fuel_tank", 3785) if spec_data else 3785
                )

            model_haulers.append(hauler)

    model["haulers"] = model_haulers

    # Rebuild operations with hauler group mapping for accurate material schedules
    if model_haulers:
        model["operations"] = create_operations_structure(
            routes,
            load_zones,
            dump_zones,
            model_haulers,
            telemetry_data=telemetry_data,
            coordinates_in_meters=coordinates_in_meters,
            machine_id_to_hauler_group=machine_id_to_hauler_group,
            schedule_name="Material Schedule 1",
            scheduling_method="grouped_assignment",
            material=material,
            density=density,
            zone_material_map=zone_material_map,
        )

    # Build loaders list from load_zones (one loader per load_zone)
    model_loaders = []
    if load_zones and default_loader_machine_list_id is not None:
        # Get default loader spec for configured string
        default_loader_spec = machine_list_loaders[0] if machine_list_loaders else None
        loader_model_name = (
            default_loader_spec.get("name", "Unknown")
            if default_loader_spec
            else "Unknown"
        )
        loader_model_id = (
            default_loader_spec.get("model_id", "") if default_loader_spec else ""
        )

        loader_id = 1
        for lz in load_zones:
            lz_id = lz.get("id")
            lz.get("name", f"Load zone {lz_id}")

            # Get number of spots from load zone settings
            lz_settings = lz.get("settings", {})
            n_spots = lz_settings.get("n_spots", 1)
            assigned_spots = list(range(1, n_spots + 1)) if n_spots > 0 else [1]

            loader = {
                "id": loader_id,
                "name": f"Loader {loader_id}",
                "key": "loaders",
                "machine_id": default_loader_machine_list_id,
                "configured": f"{loader_model_name} (ID: {loader_model_id})",
                "used_for": "Truck Loading",
                "fill_factor_pct": 1.0,
                "initial_charge_fuel_levels_pct": 95,
                "initial_conditions": {
                    "load_zone_id": lz_id,
                    "assigned_load_spots": assigned_spots,
                },
                "is_deactive": False,
            }

            model_loaders.append(loader)
            loader_id += 1

    model["loaders"] = model_loaders

    # Update camera position
    if nodes:
        eastings = [n["coords"][0] for n in nodes]
        northings = [n["coords"][1] for n in nodes]
        elevations = [n["coords"][2] for n in nodes]

        center_x = (min(eastings) + max(eastings)) / 2
        center_y = (min(northings) + max(northings)) / 2
        center_z = (min(elevations) + max(elevations)) / 2
        span = max(max(eastings) - min(eastings), max(northings) - min(northings))

        model["cameraPosition"] = {"x": center_x, "y": center_z + span, "z": center_y}
        model["controlTarget"] = {"x": center_x, "y": center_z, "z": center_y}

    return model
