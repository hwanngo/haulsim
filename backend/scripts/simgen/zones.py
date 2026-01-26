"""
Zone detection and conversion — extracted from simulation_generator.py (behavior-preserving).
"""

import math
from collections import defaultdict
from typing import Dict, List, Tuple

from backend.scripts.simgen.constants import (
    LOADED_PAYLOAD_THRESHOLD,
    READER_ZONE_TO_ROAD_MAX_DIST_M,
    STOPPED_SPEED_THRESHOLD,
    ZONE_TO_ROAD_MAX_DIST_M,
)

__all__ = [
    "convert_reader_zones_to_model",
    "detect_zones",
]


def convert_reader_zones_to_model(
    reader_zones: List,
    nodes: List[Dict],
    roads: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """
    Convert Reader.Zone objects to model zone dicts (same format as detect_zones output).

    Args:
        reader_zones: Zone objects from Reader.py (with zoneType, centroid, points)
        nodes: Road network nodes
        roads: Road network roads

    Returns:
        Tuple of (load_zones, dump_zones)
    """

    if not reader_zones:
        return [], []

    # Build node lookup for nearest road endpoint search
    node_lookup = {n["id"]: n for n in nodes}
    road_endpoints = []
    for road in roads:
        if len(road["nodes"]) >= 2:
            start_node = node_lookup.get(road["nodes"][0])
            end_node = node_lookup.get(road["nodes"][-1])
            if start_node and end_node:
                road_endpoints.append(
                    {
                        "road_id": road["id"],
                        "start": tuple(start_node["coords"]),
                        "end": tuple(end_node["coords"]),
                        "start_node_id": road["nodes"][0],
                        "end_node_id": road["nodes"][-1],
                    }
                )

    def find_nearest_road_endpoint(x, y):
        min_dist = float("inf")
        nearest = None
        for ep in road_endpoints:
            for label in ("start", "end"):
                node_id_key = f"{label}_node_id"
                dx = x - ep[label][0]
                dy = y - ep[label][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < min_dist:
                    min_dist = dist
                    nearest = {
                        "road_id": ep["road_id"],
                        "node_id": ep[node_id_key],
                        "distance": dist,
                    }
        return nearest

    load_zones = []
    dump_zones = []
    load_id = 1
    dump_id = 1

    for zone in reader_zones:
        # Compute centroid from zone points
        if hasattr(zone, "centroid") and zone.centroid:
            cx, cy = zone.centroid[0][0], zone.centroid[0][1]
            avg_z = zone.centroid[0][2] if len(zone.centroid[0]) > 2 else 0.0
        elif hasattr(zone, "points") and zone.points:
            xs = [p[0] for p in zone.points]
            ys = [p[1] for p in zone.points]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            zs = [p[2] for p in zone.points if len(p) > 2]
            avg_z = sum(zs) / len(zs) if zs else 0.0
        else:
            continue

        nearest = find_nearest_road_endpoint(cx, cy)
        if nearest is None or nearest["distance"] > READER_ZONE_TO_ROAD_MAX_DIST_M:
            continue

        zone_settings = {
            "n_spots": 1,
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
            "zonetype": "standard",
            "inroad_ids": [nearest["road_id"]],
            "outroad_ids": [nearest["road_id"]],
            "innode_ids": [nearest["node_id"]],
            "outnode_ids": [nearest["node_id"]],
        }

        zone_type_name = (
            zone.zoneType.value
            if hasattr(zone.zoneType, "value")
            else str(zone.zoneType)
        )

        if zone_type_name == "LOAD":
            zone_dict = {
                "id": load_id,
                "name": f"Load zone {load_id}",
                "keys": "load_zones",
                "is_generated": True,
                "connector_zone_data": [],
                "settings": zone_settings,
                "detected_location": {"x": cx, "y": cy, "z": avg_z},
            }
            load_zones.append(zone_dict)
            load_id += 1
        elif zone_type_name == "DUMP":
            zone_dict = {
                "id": dump_id,
                "name": f"Dump zone {dump_id}",
                "is_generated": True,
                "connector_zone_data": [],
                "settings": zone_settings,
                "detected_location": {"x": cx, "y": cy, "z": avg_z},
            }
            dump_zones.append(zone_dict)
            dump_id += 1

    return load_zones, dump_zones


def detect_zones(
    telemetry_data: List[Tuple],
    nodes: List[Dict],
    roads: List[Dict],
    grid_size: float = 10.0,
    min_stop_count: int = 20,
    coordinates_in_meters: bool = False,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Detect load/dump zones from stopped points in telemetry.

    Args:
        telemetry_data: Telemetry data tuples
        nodes: List of nodes
        roads: List of roads
        grid_size: Grid size for zone detection
        min_stop_count: Minimum stop count for zone detection
        coordinates_in_meters: If True, coordinates are already in meters (for imported data).
                              If False, coordinates are in millimeters (for database data).

    Returns:
        Tuple of (load_zones, dump_zones)
    """
    if not telemetry_data:
        return [], []

    # Grid for stopped points
    grid = {}

    for row in telemetry_data:
        actual_speed = row[8] if len(row) > 8 else None
        payload = row[13] if len(row) > 13 else None

        if actual_speed is not None and actual_speed <= STOPPED_SPEED_THRESHOLD:
            # M3: guard with `is not None` so a real coordinate of 0 is kept.
            if coordinates_in_meters:
                # Coordinates already in meters
                x = float(row[4]) if row[4] is not None else 0
                y = float(row[5]) if row[5] is not None else 0
                z = float(row[6]) if row[6] is not None else 0
            else:
                # Coordinates in millimeters - convert to meters
                x = row[4] / 1000.0 if row[4] is not None else 0
                y = row[5] / 1000.0 if row[5] is not None else 0
                z = row[6] / 1000.0 if row[6] is not None else 0

            grid_x = round(x / grid_size) * grid_size
            grid_y = round(y / grid_size) * grid_size
            key = (grid_x, grid_y)

            if key not in grid:
                grid[key] = {"points": [], "payloads": [], "elevations": []}

            grid[key]["points"].append((x, y, z))
            grid[key]["elevations"].append(z)

            if payload is not None and 0 <= payload <= 100:
                grid[key]["payloads"].append(payload)

    # M4: classify zones by the empty->loaded transition, not the mean payload
    # at the stop. A truck parked at a load zone AFTER loading has payload ~100,
    # which inflates the cell's mean payload and previously mislabelled the load
    # zone as a dump zone (and vice-versa).
    #
    # Walk each machine's telemetry in time order, detect payload transitions,
    # and attribute each transition to the grid cell where it occurs:
    #   empty -> loaded  => evidence the cell is a LOAD zone
    #   loaded -> empty  => evidence the cell is a DUMP zone
    transition_counts = defaultdict(lambda: {"load": 0, "dump": 0})

    def _cell_key(rx, ry):
        return (round(rx / grid_size) * grid_size, round(ry / grid_size) * grid_size)

    machine_series = defaultdict(list)
    for row in telemetry_data:
        machine_id = row[0] if len(row) > 0 else None
        if machine_id is None:
            continue
        timestamp = row[3] if len(row) > 3 else 0
        payload = row[13] if len(row) > 13 else None
        if coordinates_in_meters:
            cx = float(row[4]) if len(row) > 4 and row[4] is not None else 0
            cy = float(row[5]) if len(row) > 5 and row[5] is not None else 0
        else:
            cx = row[4] / 1000.0 if len(row) > 4 and row[4] is not None else 0
            cy = row[5] / 1000.0 if len(row) > 5 and row[5] is not None else 0
        machine_series[machine_id].append((timestamp, cx, cy, payload))

    for machine_id, series in machine_series.items():
        series.sort(key=lambda p: p[0])
        prev_loaded = None
        for _, cx, cy, payload in series:
            if payload is None:
                continue
            is_loaded = payload >= LOADED_PAYLOAD_THRESHOLD
            if prev_loaded is not None and is_loaded != prev_loaded:
                key = _cell_key(cx, cy)
                if not prev_loaded and is_loaded:
                    transition_counts[key]["load"] += 1
                elif prev_loaded and not is_loaded:
                    transition_counts[key]["dump"] += 1
            prev_loaded = is_loaded

    # Build node lookup for road endpoint detection
    node_lookup = {n["id"]: n for n in nodes}
    road_endpoints = []
    for road in roads:
        if len(road["nodes"]) >= 2:
            start_node = node_lookup.get(road["nodes"][0])
            end_node = node_lookup.get(road["nodes"][-1])
            if start_node and end_node:
                road_endpoints.append(
                    {
                        "road_id": road["id"],
                        "start": tuple(start_node["coords"]),
                        "end": tuple(end_node["coords"]),
                        "start_node_id": road["nodes"][0],
                        "end_node_id": road["nodes"][-1],
                    }
                )

    def find_nearest_road_endpoint(x, y):
        min_dist = float("inf")
        nearest = None
        for ep in road_endpoints:
            dist_end = math.sqrt((x - ep["end"][0]) ** 2 + (y - ep["end"][1]) ** 2)
            if dist_end < min_dist:
                min_dist = dist_end
                nearest = {
                    "road_id": ep["road_id"],
                    "node_id": ep["end_node_id"],
                    "distance": dist_end,
                }
            dist_start = math.sqrt(
                (x - ep["start"][0]) ** 2 + (y - ep["start"][1]) ** 2
            )
            if dist_start < min_dist:
                min_dist = dist_start
                nearest = {
                    "road_id": ep["road_id"],
                    "node_id": ep["start_node_id"],
                    "distance": dist_start,
                }
        return nearest

    # Create zones
    load_zones = []
    dump_zones = []
    load_id = 1
    dump_id = 1

    for (grid_x, grid_y), data in grid.items():
        if len(data["points"]) < min_stop_count:
            continue

        avg_z = (
            sum(data["elevations"]) / len(data["elevations"])
            if data["elevations"]
            else 0
        )
        avg_payload = (
            sum(data["payloads"]) / len(data["payloads"]) if data["payloads"] else 50
        )

        nearest = find_nearest_road_endpoint(grid_x, grid_y)
        if nearest is None or nearest["distance"] > ZONE_TO_ROAD_MAX_DIST_M:
            continue

        # M4: classify by observed transitions first; fall back to mean payload
        # only when no transitions were seen for this cell.
        counts = transition_counts.get((grid_x, grid_y), {"load": 0, "dump": 0})
        if counts["load"] != counts["dump"]:
            is_load_zone = counts["load"] > counts["dump"]
        else:
            is_load_zone = avg_payload <= LOADED_PAYLOAD_THRESHOLD

        zone_settings = {
            "n_spots": 1,
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
            "zonetype": "standard",
            "inroad_ids": [nearest["road_id"]],
            "outroad_ids": [nearest["road_id"]],
            "innode_ids": [nearest["node_id"]],
            "outnode_ids": [nearest["node_id"]],
        }

        if is_load_zone:  # Load zone
            zone = {
                "id": load_id,
                "name": f"Load zone {load_id}",
                "keys": "load_zones",
                "is_generated": True,
                "connector_zone_data": [],
                "settings": zone_settings,
                "detected_location": {"x": grid_x, "y": grid_y, "z": avg_z},
            }
            load_zones.append(zone)
            load_id += 1
        else:  # Dump zone
            zone = {
                "id": dump_id,
                "name": f"Dump zone {dump_id}",
                "is_generated": True,
                "connector_zone_data": [],
                "settings": zone_settings,
                "detected_location": {"x": grid_x, "y": grid_y, "z": avg_z},
            }
            dump_zones.append(zone)
            dump_id += 1

    return load_zones, dump_zones
