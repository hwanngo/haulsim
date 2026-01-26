"""
Route creation and zone setting updates — extracted from simulation_generator.py (behavior-preserving).
"""

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from backend.scripts.simgen.constants import *  # noqa: F401, F403

__all__ = [
    "create_routes",
    "get_path_entry_exit_nodes",
    "update_zone_settings_for_routes",
]


def create_routes(
    load_zones: List[Dict],
    dump_zones: List[Dict],
    roads: List[Dict],
    nodes: List[Dict],
    observed_pairs: Optional[Set[Tuple[int, int]]] = None,
) -> List[Dict]:
    """
    Create routes connecting load zones to dump zones.

    A route defines the path a hauler takes:
    - Load at load_zone
    - Haul (loaded) via haul roads to dump_zone
    - Dump at dump_zone
    - Return (empty) via return roads back to load_zone

    Args:
        load_zones: List of load zone dictionaries
        dump_zones: List of dump zone dictionaries
        roads: List of road dictionaries
        nodes: List of node dictionaries

    Returns:
        List of route dictionaries with structure:
        {
            "id": int,
            "name": str,
            "haul": [road_ids],
            "return": [road_ids],
            "load_zone": int,
            "dump_zone": int
        }
    """
    if not load_zones or not dump_zones or not roads:
        return []

    # Build node lookup
    {n["id"]: n for n in nodes}

    # Build road lookup and connection graph
    road_lookup = {r["id"]: r for r in roads}

    # Build graph: node_id -> list of (road_id, other_endpoint_node_id)
    # Each road connects its first node to its last node
    node_to_roads = {}
    for road in roads:
        if len(road["nodes"]) < 2:
            continue
        start_node = road["nodes"][0]
        end_node = road["nodes"][-1]

        if start_node not in node_to_roads:
            node_to_roads[start_node] = []
        if end_node not in node_to_roads:
            node_to_roads[end_node] = []

        # Road can be traversed in both directions (2-way roads)
        node_to_roads[start_node].append((road["id"], end_node))
        node_to_roads[end_node].append((road["id"], start_node))

    def find_path(start_node_id: int, end_node_id: int) -> List[int]:
        """
        Find a path of roads from start_node to end_node using BFS.
        Returns list of road IDs forming the path.
        """
        if start_node_id == end_node_id:
            return []

        if start_node_id not in node_to_roads:
            return []

        # BFS to find path
        queue = deque([(start_node_id, [])])  # (current_node, road_path)
        visited = {start_node_id}

        while queue:
            current_node, path = queue.popleft()

            if current_node not in node_to_roads:
                continue

            for road_id, next_node in node_to_roads[current_node]:
                if next_node in visited:
                    continue

                new_path = path + [road_id]

                if next_node == end_node_id:
                    return new_path

                visited.add(next_node)
                queue.append((next_node, new_path))

        return []

    routes = []
    route_id = 1

    for lz in load_zones:
        lz_id = lz["id"]
        lz_name = lz.get("name", f"Load zone {lz_id}")
        lz_settings = lz.get("settings", {})
        lz_outroad_ids = lz_settings.get("outroad_ids", [])
        lz_outnode_ids = lz_settings.get("outnode_ids", [])
        lz_inroad_ids = lz_settings.get("inroad_ids", [])
        lz_innode_ids = lz_settings.get("innode_ids", [])

        for dz in dump_zones:
            dz_id = dz["id"]
            # Skip pairs not observed in telemetry (when observed_pairs filter is active)
            if observed_pairs is not None and (lz_id, dz_id) not in observed_pairs:
                continue
            dz_name = dz.get("name", f"Dump zone {dz_id}")
            dz_settings = dz.get("settings", {})
            dz_inroad_ids = dz_settings.get("inroad_ids", [])
            dz_innode_ids = dz_settings.get("innode_ids", [])
            dz_outroad_ids = dz_settings.get("outroad_ids", [])
            dz_outnode_ids = dz_settings.get("outnode_ids", [])

            # Determine haul path: from load_zone exit to dump_zone entry
            haul_roads = []
            haul_path_found = False
            if lz_outroad_ids and dz_inroad_ids:
                # If both zones connect to the same road, that's the haul road
                if lz_outroad_ids[0] == dz_inroad_ids[0]:
                    haul_roads = [lz_outroad_ids[0]]
                    haul_path_found = True
                else:
                    # Try to find path from load_zone exit node to dump_zone entry node
                    if lz_outnode_ids and dz_innode_ids:
                        path = find_path(lz_outnode_ids[0], dz_innode_ids[0])
                        if path:
                            haul_roads = path
                            haul_path_found = True
                        else:
                            # Fallback: try to find connecting path between roads
                            lz_road = road_lookup.get(lz_outroad_ids[0])
                            dz_road = road_lookup.get(dz_inroad_ids[0])
                            if lz_road and dz_road:
                                # Try all endpoint combinations
                                lz_endpoints = [
                                    lz_road["nodes"][0],
                                    lz_road["nodes"][-1],
                                ]
                                dz_endpoints = [
                                    dz_road["nodes"][0],
                                    dz_road["nodes"][-1],
                                ]
                                for lz_ep in lz_endpoints:
                                    for dz_ep in dz_endpoints:
                                        connecting_path = find_path(lz_ep, dz_ep)
                                        if connecting_path:
                                            # Build full path: lz_outroad + connecting + dz_inroad
                                            haul_roads = (
                                                lz_outroad_ids
                                                + connecting_path
                                                + [
                                                    r
                                                    for r in dz_inroad_ids
                                                    if r not in lz_outroad_ids
                                                    and r not in connecting_path
                                                ]
                                            )
                                            haul_path_found = True
                                            break
                                    if haul_path_found:
                                        break
                            if not haul_path_found:
                                # Last fallback: just use lz_outroad (partial path)
                                haul_roads = lz_outroad_ids
                    else:
                        haul_roads = lz_outroad_ids
            elif lz_outroad_ids:
                haul_roads = lz_outroad_ids

            # Determine return path: from dump_zone exit to load_zone entry
            return_roads = []
            return_path_found = False
            if dz_outroad_ids and lz_inroad_ids:
                # If both zones connect to the same road, that's the return road
                if dz_outroad_ids[0] == lz_inroad_ids[0]:
                    return_roads = [dz_outroad_ids[0]]
                    return_path_found = True
                else:
                    # Try to find path from dump_zone exit node to load_zone entry node
                    if dz_outnode_ids and lz_innode_ids:
                        path = find_path(dz_outnode_ids[0], lz_innode_ids[0])
                        if path:
                            return_roads = path
                            return_path_found = True
                        else:
                            # Fallback: try to find connecting path between roads
                            dz_road = road_lookup.get(dz_outroad_ids[0])
                            lz_road = road_lookup.get(lz_inroad_ids[0])
                            if dz_road and lz_road:
                                # Try all endpoint combinations
                                dz_endpoints = [
                                    dz_road["nodes"][0],
                                    dz_road["nodes"][-1],
                                ]
                                lz_endpoints = [
                                    lz_road["nodes"][0],
                                    lz_road["nodes"][-1],
                                ]
                                for dz_ep in dz_endpoints:
                                    for lz_ep in lz_endpoints:
                                        connecting_path = find_path(dz_ep, lz_ep)
                                        if connecting_path:
                                            # Build full path: dz_outroad + connecting + lz_inroad
                                            return_roads = (
                                                dz_outroad_ids
                                                + connecting_path
                                                + [
                                                    r
                                                    for r in lz_inroad_ids
                                                    if r not in dz_outroad_ids
                                                    and r not in connecting_path
                                                ]
                                            )
                                            return_path_found = True
                                            break
                                    if return_path_found:
                                        break
                            if not return_path_found:
                                # Last fallback: just use dz_outroad (partial path)
                                return_roads = dz_outroad_ids
                    else:
                        return_roads = dz_outroad_ids
            elif dz_outroad_ids:
                return_roads = dz_outroad_ids

            # Skip routes with no valid paths
            if not haul_roads and not return_roads:
                print(
                    f"    Warning: No path found for route {lz_name} to {dz_name}, skipping"
                )
                continue

            # Validate route connectivity
            def validate_path_connectivity(path: List[int], path_name: str) -> bool:
                """Check if consecutive roads in path share a common endpoint."""
                if len(path) <= 1:
                    return True
                for i in range(len(path) - 1):
                    road_a = road_lookup.get(path[i])
                    road_b = road_lookup.get(path[i + 1])
                    if not road_a or not road_b:
                        continue
                    # Get endpoints of both roads
                    a_endpoints = {road_a["nodes"][0], road_a["nodes"][-1]}
                    b_endpoints = {road_b["nodes"][0], road_b["nodes"][-1]}
                    # Check if they share any endpoint
                    if not a_endpoints.intersection(b_endpoints):
                        print(
                            f"    Warning: {path_name} roads {path[i]} and {path[i + 1]} do not share a common node"
                        )
                        return False
                return True

            haul_valid = validate_path_connectivity(
                haul_roads, f"Route '{lz_name} to {dz_name}' haul"
            )
            return_valid = validate_path_connectivity(
                return_roads, f"Route '{lz_name} to {dz_name}' return"
            )

            # Only add route if both paths are valid (or empty)
            if not haul_valid or not return_valid:
                print(
                    f"    Warning: Route {lz_name} to {dz_name} has invalid paths, skipping"
                )
                continue

            route = {
                "id": route_id,
                "name": f"{lz_name} to {dz_name}",
                "haul": haul_roads,
                "return": return_roads,
                "load_zone": lz_id,
                "dump_zone": dz_id,
            }
            routes.append(route)
            route_id += 1

    return routes


def get_path_entry_exit_nodes(
    path: List[int],
    roads: List[Dict],
    start_node_hint: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Determine the entry and exit nodes of a path (sequence of roads).

    For a valid path, consecutive roads must share a common endpoint.
    This function traces through the path to find:
    - Entry node: The starting node where we enter the first road
    - Exit node: The ending node where we leave the last road

    Args:
        path: List of road IDs forming the path
        roads: List of road dictionaries
        start_node_hint: Optional hint for which node to start from (for single road paths)

    Returns:
        Tuple of (entry_node_id, exit_node_id), or (None, None) if path is invalid
    """
    if not path:
        return None, None

    road_lookup = {r["id"]: r for r in roads}

    if len(path) == 1:
        # Single road - use hint if provided, otherwise return both endpoints
        road = road_lookup.get(path[0])
        if not road or len(road["nodes"]) < 2:
            return None, None

        start_node = road["nodes"][0]
        end_node = road["nodes"][-1]

        # If hint is provided and matches one endpoint, use it to determine direction
        if start_node_hint is not None:
            if start_node_hint == start_node:
                return start_node, end_node
            elif start_node_hint == end_node:
                return end_node, start_node

        # Default: first node is entry, last node is exit
        return start_node, end_node

    # For multiple roads, trace through to find entry/exit
    # Start by determining which endpoint of first road connects to second road
    first_road = road_lookup.get(path[0])
    second_road = road_lookup.get(path[1])

    if not first_road or not second_road:
        return None, None

    first_endpoints = {first_road["nodes"][0], first_road["nodes"][-1]}
    second_endpoints = {second_road["nodes"][0], second_road["nodes"][-1]}

    shared = first_endpoints.intersection(second_endpoints)
    if not shared:
        return None, None

    # The shared node is where first road exits
    shared_node = shared.pop()
    # Entry node is the other endpoint of first road
    entry_node = (
        first_road["nodes"][-1]
        if first_road["nodes"][0] == shared_node
        else first_road["nodes"][0]
    )

    # Now trace through to find exit node
    current_node = shared_node
    for i in range(1, len(path)):
        road = road_lookup.get(path[i])
        if not road:
            return entry_node, None

        # Determine which direction we traverse this road
        if road["nodes"][0] == current_node:
            # Traverse forward
            current_node = road["nodes"][-1]
        elif road["nodes"][-1] == current_node:
            # Traverse backward
            current_node = road["nodes"][0]
        else:
            # Discontinuity - road doesn't connect
            return entry_node, None

    return entry_node, current_node


def update_zone_settings_for_routes(
    routes: List[Dict],
    load_zones: List[Dict],
    dump_zones: List[Dict],
    roads: List[Dict],
) -> None:
    """
    Update zone innode_ids and outnode_ids based on actual route paths.

    This ensures zone entry/exit nodes match the route definitions to avoid
    discontinuity errors during validation.

    For each route:
    - Load zone outnode_ids should include the entry node of first haul road
    - Dump zone innode_ids should include the exit node of last haul road
    - Dump zone outnode_ids should include the entry node of first return road
    - Load zone innode_ids should include the exit node of last return road

    Args:
        routes: List of route dictionaries
        load_zones: List of load zone dictionaries (will be modified in place)
        dump_zones: List of dump zone dictionaries (will be modified in place)
        roads: List of road dictionaries
    """
    if not routes or not roads:
        return

    # Build zone lookups
    lz_lookup = {z["id"]: z for z in load_zones}
    dz_lookup = {z["id"]: z for z in dump_zones}

    for route in routes:
        lz_id = route.get("load_zone")
        dz_id = route.get("dump_zone")
        haul_path = route.get("haul", [])
        return_path = route.get("return", [])

        lz = lz_lookup.get(lz_id)
        dz = dz_lookup.get(dz_id)

        if not lz or not dz:
            continue

        # Ensure settings exist
        if "settings" not in lz:
            lz["settings"] = {}
        if "settings" not in dz:
            dz["settings"] = {}

        # Get existing zone node hints for single road cases
        lz_outnode_hint = lz["settings"].get("outnode_ids", [None])[0]
        dz_outnode_hint = dz["settings"].get("outnode_ids", [None])[0]

        # Process haul path: load zone -> dump zone
        if haul_path:
            haul_entry, haul_exit = get_path_entry_exit_nodes(
                haul_path, roads, start_node_hint=lz_outnode_hint
            )

            if haul_entry is not None:
                # Update load zone outnode_ids
                outnode_ids = lz["settings"].get("outnode_ids", [])
                if haul_entry not in outnode_ids:
                    outnode_ids.append(haul_entry)
                lz["settings"]["outnode_ids"] = outnode_ids

            if haul_exit is not None:
                # Update dump zone innode_ids
                innode_ids = dz["settings"].get("innode_ids", [])
                if haul_exit not in innode_ids:
                    innode_ids.append(haul_exit)
                dz["settings"]["innode_ids"] = innode_ids

        # Process return path: dump zone -> load zone
        if return_path:
            return_entry, return_exit = get_path_entry_exit_nodes(
                return_path, roads, start_node_hint=dz_outnode_hint
            )

            if return_entry is not None:
                # Update dump zone outnode_ids
                outnode_ids = dz["settings"].get("outnode_ids", [])
                if return_entry not in outnode_ids:
                    outnode_ids.append(return_entry)
                dz["settings"]["outnode_ids"] = outnode_ids

            if return_exit is not None:
                # Update load zone innode_ids
                innode_ids = lz["settings"].get("innode_ids", [])
                if return_exit not in innode_ids:
                    innode_ids.append(return_exit)
                lz["settings"]["innode_ids"] = innode_ids
