"""
DES inputs generation — extracted from simulation_generator.py (behavior-preserving).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from backend.scripts.simgen.constants import *  # noqa: F401, F403
from backend.scripts.simgen.specs import (
    _create_default_hauler_spec,
    _create_default_loader_spec,
)
from backend.scripts.simgen.operations import (
    analyze_hauler_trips_from_telemetry,
    build_machine_id_to_hauler_group,
    create_material_schedule_from_trips,
)

__all__ = [
    "_create_des_operations",
    "create_des_inputs",
]


def _create_des_operations(
    des_routes: List[Dict],
    des_load_zones: List[Dict],
    des_dump_zones: List[Dict],
    haulers: List[Dict] = None,
    model_load_zones: List[Dict] = None,
    model_dump_zones: List[Dict] = None,
    telemetry_data: List[Tuple] = None,
    coordinates_in_meters: bool = False,
    machine_id_to_hauler_group: Dict[int, int] = None,
    model_routes: List[Dict] = None,
    material: str = DEFAULT_MATERIAL,
    density: float = DEFAULT_MATERIAL_DENSITY,
    zone_material_map: Optional[Dict[str, "Tuple[str, float]"]] = None,
) -> Dict:
    """
    Create operations structure for DES inputs.

    If telemetry_data is provided, analyzes actual hauler trips to determine
    which haulers traveled between which zones.

    Args:
        des_routes: List of DES route dictionaries (with start_zone/end_zone format)
        des_load_zones: List of DES load zone dictionaries
        des_dump_zones: List of DES dump zone dictionaries
        haulers: Optional list of hauler dictionaries
        model_load_zones: Model load zones with detected_location (for trip analysis)
        model_dump_zones: Model dump zones with detected_location (for trip analysis)
        telemetry_data: Optional telemetry data for actual trip analysis
        coordinates_in_meters: Whether telemetry coordinates are in meters
        machine_id_to_hauler_group: Mapping of machine_id to hauler group_id
        model_routes: Model routes for route matching in material schedule

    Returns:
        Operations dictionary with material_schedules
    """
    # Try to analyze actual trips from telemetry data first
    material_data = []

    if telemetry_data and model_load_zones and model_dump_zones:
        trips_by_machine = analyze_hauler_trips_from_telemetry(
            telemetry_data, model_load_zones, model_dump_zones, coordinates_in_meters
        )
        if trips_by_machine:
            material_data = create_material_schedule_from_trips(
                trips_by_machine,
                routes=model_routes,
                haulers=haulers,
                machine_id_to_hauler_group=machine_id_to_hauler_group,
                load_zones=model_load_zones,
                dump_zones=model_dump_zones,
                default_material=material,
                default_density=density,
                **(
                    {"zone_material_map": zone_material_map}
                    if zone_material_map is not None
                    else {}
                ),
            )

    # Fallback: generate from DES routes
    if not material_data:
        # Build zone name lookups
        lz_lookup = {
            z["id"]: z.get("name", f"Load zone {z['id']}") for z in des_load_zones
        }
        dz_lookup = {
            z["id"]: z.get("name", f"Dump zone {z['id']}") for z in des_dump_zones
        }

        # Count haulers per route if available
        haulers_per_route = {}
        if haulers:
            for hauler in haulers:
                route_id = hauler.get("initial_conditions", {}).get("route_id")
                if route_id is not None:
                    haulers_per_route[route_id] = haulers_per_route.get(
                        route_id, 0
                    ) + hauler.get("number_of_haulers", 1)

        # Default haulers per route
        total_haulers = (
            sum(haulers_per_route.values())
            if haulers_per_route
            else len(des_routes) * 4
        )
        default_haulers = max(1, total_haulers // len(des_routes)) if des_routes else 4

        for idx, route in enumerate(des_routes, start=1):
            # Extract zone IDs from DES route format
            lz_id = route.get("start_zone", {}).get("id")
            dz_id = route.get("end_zone", {}).get("id")

            lz_name = lz_lookup.get(lz_id, f"Load zone {lz_id}")
            dz_name = dz_lookup.get(dz_id, f"Dump zone {dz_id}")
            route_name = route.get("name", "")

            # Get hauler count for this route
            num_haulers = haulers_per_route.get(route.get("id"), default_haulers)

            item = {
                "id": idx,
                "load_zone": lz_name,
                "dump_zone": dz_name,
                "route": route_name,
                "auto_generate_route": True,
                "material": material,
                "density": density,
                "num_of_hauler": num_haulers,
                "assigned_machine_type": "Hauler",
                "multiple_routes": False,
                "hauler_group_id": 1,
            }
            material_data.append(item)

    return {
        "material_schedules": {
            "selected_material": 1,
            "all_material_schedule": [
                {
                    "id": 1,
                    "name": "Material Schedule 1",
                    "hauler_assignment": {"scheduling_method": "grouped_assignment"},
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


def create_des_inputs(
    model: Dict,
    machines: Dict[int, Dict],
    site_name: str,
    sim_time: int = 480,
    machines_with_events: Optional[Set[int]] = None,
    machine_templates: Optional[Dict[str, Any]] = None,
    telemetry_data: Optional[List[Tuple]] = None,
    coordinates_in_meters: bool = False,
    material: str = DEFAULT_MATERIAL,
    density: Optional[float] = None,
    material_catalog: Optional[Dict[str, Dict]] = None,
    zone_id_to_key: Optional[Dict[int, str]] = None,
    zone_material_map: Optional[Dict[str, "Tuple[str, float]"]] = None,
) -> Dict:
    """
    Create DES Inputs structure from model and machine data.

    Args:
        model: Model dictionary with nodes, roads, zones
        machines: Machine info dictionary
        site_name: Site name
        sim_time: Simulation time in minutes
        machines_with_events: Set of machine IDs that have events data
        machine_templates: Machine templates loaded from JSON file
        telemetry_data: Optional telemetry data for actual trip analysis
        coordinates_in_meters: Whether telemetry coordinates are in meters
        material: Internal material name (e.g. "copper_ore"); must match an entry in materials.json
        density: Material loose density in kg/m³; resolved from materials.json when None

    Returns:
        DES Inputs dictionary
    """
    from backend.scripts.simgen.loaders import (
        resolve_material_density,
        material_catalog_key,
        build_material_properties,
        deep_copy_dict,
        merge_dict,
    )

    if density is None:
        density = resolve_material_density(material)
    _catalog_key = material_catalog_key(material, density)

    nodes = model.get("nodes", [])
    roads = model.get("roads", [])
    load_zones = model.get("load_zones", [])
    dump_zones = model.get("dump_zones", [])

    # Convert zones to DES format
    des_load_zones = []
    for zone in load_zones:
        zone_key = (
            zone_id_to_key.get(zone["id"], _catalog_key)
            if zone_id_to_key
            else _catalog_key
        )
        des_zone = {
            "id": zone["id"],
            "name": zone["name"],
            "material": [zone_key],
            "terminal_zone": False,
            # L2: "spots" is unconditionally overwritten below (zone-road
            # generation) with the correct entry/spotting/exit road ids, so the
            # placeholder set here was dead. Omitted; downstream reads use .get().
        }
        des_load_zones.append(des_zone)

    des_dump_zones = []
    for zone in dump_zones:
        des_zone = {
            "id": zone["id"],
            "name": zone["name"],
            "terminal_zone": False,
            # L2: see load-zone note above; "spots" is overwritten downstream.
        }
        des_dump_zones.append(des_zone)

    # Create hauler specs and haulers list
    # Group specs by model type (machines with same type_name share one spec)
    hauler_specs = {}
    loader_specs = {}
    haulers = []
    hauler_id = 1
    uid_base = HAULER_UID_BASE

    # Track model types to spec IDs mapping
    model_to_spec_id = {}  # type_name -> spec_id
    spec_id = 1

    # Load templates from file or use defaults
    templates = machine_templates or {}
    hauler_template = templates.get("hauler_template", {})
    electric_hauler_overrides = templates.get("electric_hauler_overrides", {})
    hauler_entry_template = templates.get("hauler_entry_template", {})
    electric_hauler_entry_overrides = templates.get(
        "electric_hauler_entry_overrides", {}
    )
    loader_template = templates.get("loader_template", {})

    # Only process machines that have events data
    for machine_id, machine_info in machines.items():
        # Skip machines without events
        if machines_with_events is not None and machine_id not in machines_with_events:
            continue

        machine_name = machine_info.get("name", f"Hauler_{machine_id}")
        machine_type_name = machine_info.get("type_name", "CAT 793F CMD")

        # Determine truck type
        is_electric = (
            "BEM" in machine_type_name
            or "Electric" in machine_type_name
            or "Battery" in machine_type_name
        )

        # Create spec for this model type if not exists
        if machine_type_name not in model_to_spec_id:
            # Create new hauler spec from template
            if hauler_template:
                # Use template from file
                hauler_spec = deep_copy_dict(hauler_template)
                hauler_machine = hauler_spec.get("machine", {}).get("machine", {})
                hauler_machine["ID"] = spec_id
                hauler_machine["Model"] = machine_type_name

                # Update tires ID
                for tire in hauler_spec.get("machine", {}).get("tires", []):
                    tire["ID"] = spec_id

                # Apply electric overrides if needed
                if is_electric and electric_hauler_overrides:
                    hauler_spec = merge_dict(hauler_spec, electric_hauler_overrides)
                    # Re-apply ID after merge
                    if "machine" in hauler_spec:
                        hauler_spec["machine"]["machine"]["ID"] = spec_id
                        hauler_spec["machine"]["machine"]["Model"] = machine_type_name

                hauler_specs[str(spec_id)] = hauler_spec
            else:
                # Fallback to hardcoded defaults
                hauler_specs[str(spec_id)] = _create_default_hauler_spec(
                    spec_id, machine_type_name, is_electric
                )

            model_to_spec_id[machine_type_name] = spec_id
            spec_id += 1

        # Get the spec ID for this hauler's model
        hauler_model_id = model_to_spec_id[machine_type_name]

        # Create hauler entry from template
        if hauler_entry_template:
            hauler = deep_copy_dict(hauler_entry_template)
            hauler["id"] = hauler_id
            hauler["name"] = machine_name
            hauler["model_id"] = hauler_model_id
            hauler["machine_name"] = machine_type_name
            hauler["uid"] = uid_base + hauler_id
            hauler["initial_conditions"] = {
                "route_id": 1 if roads else None,
                "road_id": roads[0]["id"] if roads else 0,
                "node_id": nodes[0]["id"] if nodes else 0,
            }

            # Apply electric overrides if needed
            if is_electric and electric_hauler_entry_overrides:
                hauler = merge_dict(hauler, electric_hauler_entry_overrides)
                # Re-apply IDs after merge
                hauler["id"] = hauler_id
                hauler["name"] = machine_name
                hauler["model_id"] = hauler_model_id
                hauler["machine_name"] = machine_type_name
                hauler["uid"] = uid_base + hauler_id
        else:
            # Fallback to hardcoded defaults
            hauler = {
                "id": hauler_id,
                "name": machine_name,
                "group": "Fleet1",
                "type": "electric" if is_electric else "diesel",
                "model_id": hauler_model_id,
                "machine_name": machine_type_name,
                "hauler_group_id": 1,
                "initial_position": 1,
                "initial_conditions": {
                    "route_id": 1 if roads else None,
                    "road_id": roads[0]["id"] if roads else 0,
                    "node_id": nodes[0]["id"] if nodes else 0,
                },
                "initial_fuel_level_pct": 0.9 if not is_electric else None,
                "initial_charge_level_pct": 0.9 if is_electric else None,
                "battery_state_of_health": 0.9 if is_electric else None,
                "EndOfLifeSOH": 84.7 if is_electric else None,
                "AvgAnnualAmbientTemp": 25,
                "CoolingActivationTemperature": 25 if is_electric else None,
                "RefridgerationActivationTemperature": 25 if is_electric else None,
                "uid": uid_base + hauler_id,
            }

        haulers.append(hauler)
        hauler_id += 1

    # Add loader spec from template
    if loader_template:
        loader_specs["1"] = deep_copy_dict(loader_template)
    else:
        # Fallback to hardcoded defaults
        loader_specs["1"] = _create_default_loader_spec()

    # Create DES nodes
    des_nodes = []
    for node in nodes:
        des_node = {
            "id": node["id"],
            "name": f"Node_{node['id']}",
            "coords": node["coords"],
            "speed_limit": node.get("speed_limit") or 40.0,
            "rolling_resistance": node.get("rolling_resistance") or 2.5,
            "banking": node.get("banking") or 0,
            "curvature": node.get("curvature") or "",
            "lane_width": node.get("lane_width") or 14,
            "traction": node.get("traction") or 0.6,
        }
        des_nodes.append(des_node)

    # Create DES roads
    des_roads = []
    for road in roads:
        des_road = {
            "id": road["id"],
            "name": road["name"],
            "nodes": road["nodes"],
            "ways_num": road.get("ways_num", 2),
            "lanes_num": road.get("lanes_num", 1),
            "speed_limit": road.get("speed_limit") or 40.0,
            "rolling_resistance": road.get("rolling_resistance") or 2.5,
            "is_generated": road.get("is_generated", False),
            "lane_width": road.get("lane_width") or 14,
            "traction_coefficient": road.get("traction_coefficient") or 0.6,
        }
        des_roads.append(des_road)

    # Generate zone-specific roads (entry, spotting, exit) for each zone
    next_node_id = max([n["id"] for n in des_nodes], default=0) + 1
    next_road_id = max([r["id"] for r in des_roads], default=0) + 1
    zone_road_offset = 20  # Offset for zone node positions (meters)
    uid_counter = 100

    # Process load zones - create entry, spotting, exit roads
    for lz in des_load_zones:
        zone_loc = None
        # Get zone location from original load_zones
        for orig_lz in load_zones:
            if orig_lz["id"] == lz["id"]:
                zone_loc = orig_lz.get("detected_location")
                break

        if not zone_loc:
            # Use first node as fallback
            if des_nodes:
                zone_loc = {
                    "x": des_nodes[0]["coords"][0],
                    "y": des_nodes[0]["coords"][1],
                    "z": des_nodes[0]["coords"][2],
                }
            else:
                continue

        x, y, z = zone_loc["x"], zone_loc["y"], zone_loc["z"]

        # Create 4 nodes for this zone: entry, spot_start, spot_end, exit
        # Spotting road needs 2 nodes (roads must have at least 2 nodes)
        entry_node_id = next_node_id
        spot_start_node_id = next_node_id + 1
        spot_end_node_id = next_node_id + 2
        exit_node_id = next_node_id + 3
        next_node_id += 4

        spot_offset = 5.0  # Small offset for spotting segment

        des_nodes.append(
            {
                "id": entry_node_id,
                "name": f"LZ{lz['id']}_Entry",
                "coords": [x - zone_road_offset, y, z],
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": spot_start_node_id,
                "name": f"LZ{lz['id']}_SpotStart",
                "coords": [x - spot_offset, y, z],
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": spot_end_node_id,
                "name": f"LZ{lz['id']}_SpotEnd",
                "coords": [x + spot_offset, y, z],
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": exit_node_id,
                "name": f"LZ{lz['id']}_Exit",
                "coords": [x + zone_road_offset, y, z],
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )

        # Create 3 roads: entry, spotting (reverse), exit
        entry_road_id = next_road_id
        spotting_road_id = next_road_id + 1
        exit_road_id = next_road_id + 2
        next_road_id += 3

        des_roads.append(
            {
                "id": entry_road_id,
                "name": f"LZ{lz['id']}_Entry_Road",
                "nodes": [entry_node_id, spot_start_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )
        des_roads.append(
            {
                "id": spotting_road_id,
                "name": f"LZ{lz['id']}_Spotting_Road",
                "nodes": [spot_start_node_id, spot_end_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )
        des_roads.append(
            {
                "id": exit_road_id,
                "name": f"LZ{lz['id']}_Exit_Road",
                "nodes": [spot_end_node_id, exit_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )

        # Update zone spots with the 3 road IDs
        lz["spots"] = [
            {
                "id": 1,
                "ess_id": None,
                "roads": [[entry_road_id, spotting_road_id, exit_road_id]],
                "uid": uid_counter,
            }
        ]
        lz["uid"] = uid_counter + 1
        uid_counter += 2

    # Process dump zones - create entry, spotting, exit roads
    for dz in des_dump_zones:
        zone_loc = None
        # Get zone location from original dump_zones
        for orig_dz in dump_zones:
            if orig_dz["id"] == dz["id"]:
                zone_loc = orig_dz.get("detected_location")
                break

        if not zone_loc:
            # Use last node as fallback
            if des_nodes:
                zone_loc = {
                    "x": des_nodes[-1]["coords"][0],
                    "y": des_nodes[-1]["coords"][1],
                    "z": des_nodes[-1]["coords"][2],
                }
            else:
                continue

        x, y, z = zone_loc["x"], zone_loc["y"], zone_loc["z"]

        # Create 4 nodes for this zone: entry, spot_start, spot_end, exit
        # Spotting road needs 2 nodes (roads must have at least 2 nodes)
        entry_node_id = next_node_id
        spot_start_node_id = next_node_id + 1
        spot_end_node_id = next_node_id + 2
        exit_node_id = next_node_id + 3
        next_node_id += 4

        spot_offset = 5.0  # Small offset for spotting segment

        des_nodes.append(
            {
                "id": entry_node_id,
                "name": f"DZ{dz['id']}_Entry",
                "coords": [x - zone_road_offset, y, z],
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": spot_start_node_id,
                "name": f"DZ{dz['id']}_SpotStart",
                "coords": [x - spot_offset, y, z],
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": spot_end_node_id,
                "name": f"DZ{dz['id']}_SpotEnd",
                "coords": [x + spot_offset, y, z],
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )
        des_nodes.append(
            {
                "id": exit_node_id,
                "name": f"DZ{dz['id']}_Exit",
                "coords": [x + zone_road_offset, y, z],
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "banking": 0,
                "curvature": "",
                "lane_width": 14,
                "traction": 0.6,
            }
        )

        # Create 3 roads: entry, spotting (reverse), exit
        entry_road_id = next_road_id
        spotting_road_id = next_road_id + 1
        exit_road_id = next_road_id + 2
        next_road_id += 3

        des_roads.append(
            {
                "id": entry_road_id,
                "name": f"DZ{dz['id']}_Entry_Road",
                "nodes": [entry_node_id, spot_start_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )
        des_roads.append(
            {
                "id": spotting_road_id,
                "name": f"DZ{dz['id']}_Spotting_Road",
                "nodes": [spot_start_node_id, spot_end_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 5.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )
        des_roads.append(
            {
                "id": exit_road_id,
                "name": f"DZ{dz['id']}_Exit_Road",
                "nodes": [spot_end_node_id, exit_node_id],
                "ways_num": 1,
                "lanes_num": 1,
                "speed_limit": 20.0,
                "rolling_resistance": 2.5,
                "is_generated": True,
                "lane_width": 14,
                "traction_coefficient": 0.6,
            }
        )

        # Update zone spots with the 3 road IDs
        dz["spots"] = [
            {
                "id": 1,
                "roads": [[entry_road_id, spotting_road_id, exit_road_id]],
                "uid": uid_counter,
            }
        ]
        dz["uid"] = uid_counter + 1
        uid_counter += 2

    # Create default loaders: one loader per spot in each load zone
    loaders: List[Dict] = []
    loader_id = 1

    # Determine default loader model and name from loader specs (if available)
    default_loader_model_id = 1 if loader_specs else None
    default_loader_machine_name = "Default_Loader"
    if loader_specs:
        default_spec = loader_specs.get(str(default_loader_model_id)) or next(
            iter(loader_specs.values())
        )
        loader_info = default_spec.get("loader", {})
        default_loader_machine_name = (
            loader_info.get("Model")
            or loader_info.get("LoaderName")
            or default_loader_machine_name
        )

    for lz in des_load_zones:
        zone_id = lz.get("id")
        for spot in lz.get("spots", []):
            spot_id = spot.get("id", 1)
            loader_entry = {
                "id": loader_id,
                "name": f"Loader_{zone_id}_{spot_id}",
                "model_id": default_loader_model_id or 1,
                "used_for": "Truck Loading",
                "machine_name": default_loader_machine_name,
                "initial_conditions": {
                    "load_zone_id": zone_id,
                    "spot_id": spot_id,
                },
                "fill_factor_pct": 1.0,
                "powernode_priority": 0,
            }
            loaders.append(loader_entry)
            loader_id += 1

    # Create routes from load zones to dump zones using pathfinding
    # Use model routes as base and add DES-specific fields
    model_routes = model.get("routes", [])
    des_routes = []
    route_uid_counter = 1000

    # Get main road IDs as fallback
    main_road_ids = [road["id"] for road in roads]

    if model_routes:
        # Use routes from model (already computed with proper pathfinding)
        for model_route in model_routes:
            route = {
                "id": model_route["id"],
                "name": model_route["name"],
                "haul": model_route["haul"],
                "return": model_route["return"],
                "start_zone": {
                    "id": model_route["load_zone"],
                    "type": "lz",
                    "uid": route_uid_counter,
                },
                "end_zone": {
                    "id": model_route["dump_zone"],
                    "type": "dz",
                    "uid": route_uid_counter + 1,
                },
                "used_by_current_MMP": True,
                "production": True,
                "uid": route_uid_counter + 2,
            }
            des_routes.append(route)
            route_uid_counter += 3
    else:
        # Fallback: create routes for all load_zone-dump_zone pairs
        route_id = 1
        for lz in des_load_zones:
            lz_id = lz["id"]
            lz_name = lz["name"]

            for dz in des_dump_zones:
                dz_id = dz["id"]
                dz_name = dz["name"]

                route = {
                    "id": route_id,
                    "name": f"{lz_name} to {dz_name}",
                    "haul": list(main_road_ids),
                    "return": list(reversed(main_road_ids)),
                    "start_zone": {
                        "id": lz_id,
                        "type": "lz",
                        "uid": route_uid_counter,
                    },
                    "end_zone": {
                        "id": dz_id,
                        "type": "dz",
                        "uid": route_uid_counter + 1,
                    },
                    "used_by_current_MMP": True,
                    "production": True,
                    "uid": route_uid_counter + 2,
                }
                des_routes.append(route)
                route_id += 1
                route_uid_counter += 3

    # If no routes created (no zones), create a default route using main roads
    if not des_routes and main_road_ids:
        des_routes.append(
            {
                "id": 1,
                "name": "Default Route",
                "haul": main_road_ids,
                "return": list(reversed(main_road_ids)),
                "start_zone": {"id": 1, "type": "lz", "uid": 1000},
                "end_zone": {"id": 1, "type": "dz", "uid": 1001},
                "used_by_current_MMP": True,
                "production": True,
                "uid": 1002,
            }
        )

    # Compute machine_id -> hauler_group mapping using the SAME basis as the DES
    # hauler-id loop above (events-only filter, machines.items() insertion order,
    # no model-name filter).  This is passed to _create_des_operations so that
    # create_material_schedule_from_trips uses the correct DES hauler id as the
    # hauler_group_id — fixing B-acc-1.
    des_mid_to_group = build_machine_id_to_hauler_group(
        machines,
        machines_with_events=machines_with_events,
        model_name_to_machine_list_id=None,  # DES hauler loop applies no model-name filter
    )

    # Build DES Inputs structure
    des_inputs = {
        "version": "CAT_2.0.2",
        "machine_specs": {
            "hauler_specs": hauler_specs,
            "loader_specs": loader_specs,
        },
        "material_properties": material_catalog
        if material_catalog is not None
        else build_material_properties(material, density),
        "map_id": 1,
        "map_translate": {
            "total_northing": 0,
            "total_easting": 0,
            "total_elevation": 0,
            "total_angle": 0,
        },
        "default_powernode_priorities": {
            "loaders": 0,
            "trolleys": 2,
            "chargers": 1,
            "crushers": 0,
        },
        "settings": {
            "sim_time": sim_time,
            "random_seed": 1234,
            "intersection_system": "simple",
            "bump_prevention": "physics_based",
            "road_network_logic": True,
            "lane_width": 14.525,
            "distance_between_lanes": 11.4,
            "driving_side": 0,
            "reduce_speed_logic": True,
            "min_foll_dist": 50,
            "verbose": False,
            "braking": True,
            "objective": "simulation",
            "log_level": "record",
            "spd_lim": 65,
            "initial_fuel_level_pct": 0.9,
            "initial_charge_level_pct": 0.9,
            "calculate_BLE": True,
        },
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
        "economic_settings": {},
        "nodes": des_nodes,
        "roads": des_roads,
        "trolleys": [],
        "load_zones": des_load_zones,
        "dump_zones": des_dump_zones,
        "crushers": [],
        "fuel_zones": [],
        "charge_zones": [],
        "service_zones": [],
        "routes": des_routes,
        "loaders": loaders,
        "haulers": haulers,
        "batteries": [],
        "esses": {},
        "electrical_distributions": [],
        "haulers_assignment": [],
        "operations": _create_des_operations(
            des_routes,
            des_load_zones,
            des_dump_zones,
            haulers,
            model_load_zones=load_zones,
            model_dump_zones=dump_zones,
            telemetry_data=telemetry_data,
            coordinates_in_meters=coordinates_in_meters,
            machine_id_to_hauler_group=des_mid_to_group,
            model_routes=model.get("routes", []),
            material=material,
            density=density,
            zone_material_map=zone_material_map,
        ),
        "override_parameters": {},
        "intersections": [],
    }

    return des_inputs
