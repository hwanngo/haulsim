"""
Road network construction and manipulation — extracted from simulation_generator.py (behavior-preserving).
"""

from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

from backend.scripts.simgen.geometry import (
    _compute_overlap_ratio,
    _compute_polyline_length,
    bboxes_overlap,
    compute_road_bounding_box,
)

__all__ = [
    "merge_overlapping_roads",
    "split_roads_at_intersections",
    "update_routes_with_split_roads",
    "find_connected_components",
]


def merge_overlapping_roads(
    nodes: List[Dict],
    roads: List[Dict],
    merge_tolerance: float = 15.0,
    min_overlap_nodes: int = 3,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Remove duplicate roads that represent the same physical road.

    Algorithm: Road Absorption
    ============================================================
    When multiple machines travel the same physical road, separate road
    polylines are created (5-20m lateral GPS offset). Instead of merging
    at the node level (which causes fragmentation and index issues), this
    function REMOVES duplicate roads entirely.

    Steps:
      1. BUILD: Create Shapely polylines for each road, compute lengths
      2. FILTER: Bounding box pre-filter for candidate pairs
      3. MEASURE: For each candidate pair, compute directed overlap ratio
         (fraction of shorter road's length within tolerance of longer road)
      4. GROUP: Build similarity graph, find connected components
         (roads in the same group represent the same physical road)
      5. SELECT: For each group, keep the longest road, mark others for removal
      6. CLEAN: Remove marked roads and unused nodes

    This approach avoids all node-level issues:
      - No node interleaving → no topology corruption
      - No section replacement → no index shift bugs
      - No shared nodes → no split fragmentation
      - Works correctly with curved roads (no direction check needed)

    Args:
        nodes: List of node dicts from create_roads_from_trajectories()
        roads: List of road dicts from create_roads_from_trajectories()
        merge_tolerance: Max distance (m) to consider roads overlapping
        min_overlap_nodes: Not used (kept for API compatibility)

    Returns:
        (updated_nodes, updated_roads) with duplicate roads removed
    """
    if not roads or len(roads) < 2:
        return nodes, roads

    print(f"    Merging overlapping roads (tolerance={merge_tolerance}m)...")

    # Step 1: Build node coord lookup and road polylines
    node_coords: Dict[int, Tuple[float, float, float]] = {}
    for node in nodes:
        node_coords[node["id"]] = tuple(node["coords"])

    road_data: Dict[int, Dict] = {}  # rid -> {coords, length, bbox}
    for road in roads:
        rid = road["id"]
        coords = [node_coords[nid] for nid in road["nodes"] if nid in node_coords]
        if len(coords) >= 2:
            length = _compute_polyline_length(coords)
            road_data[rid] = {
                "coords": coords,
                "length": length,
                "bbox": compute_road_bounding_box(coords, merge_tolerance),
            }

    # Step 2: Bounding box pre-filter for candidate pairs
    road_ids = list(road_data.keys())
    candidate_pairs = []
    for i in range(len(road_ids)):
        for j in range(i + 1, len(road_ids)):
            rid_a, rid_b = road_ids[i], road_ids[j]
            if bboxes_overlap(road_data[rid_a]["bbox"], road_data[rid_b]["bbox"]):
                candidate_pairs.append((rid_a, rid_b))

    if not candidate_pairs:
        print("      No candidate pairs found")
        return nodes, roads

    print(f"      {len(candidate_pairs)} candidate pairs (bbox filter)")

    # Step 3: Compute overlap ratios for each pair
    # An edge (A, B) means B is absorbed by A (B's overlap ratio >= threshold)
    OVERLAP_THRESHOLD = 0.7  # At least 70% of shorter road must be covered
    overlap_edges: List[Tuple[int, int]] = []  # (longer_rid, shorter_rid)

    for rid_a, rid_b in candidate_pairs:
        data_a = road_data[rid_a]
        data_b = road_data[rid_b]

        # Determine which is longer
        if data_a["length"] >= data_b["length"]:
            longer_rid, shorter_rid = rid_a, rid_b
            longer_coords, shorter_coords = data_a["coords"], data_b["coords"]
        else:
            longer_rid, shorter_rid = rid_b, rid_a
            longer_coords, shorter_coords = data_b["coords"], data_a["coords"]

        # Compute overlap: what fraction of shorter road is within tolerance of longer
        overlap_ratio = _compute_overlap_ratio(
            shorter_coords, longer_coords, merge_tolerance
        )

        if overlap_ratio >= OVERLAP_THRESHOLD:
            overlap_edges.append((longer_rid, shorter_rid))

    if not overlap_edges:
        print(f"      No roads to merge (threshold={OVERLAP_THRESHOLD:.0%})")
        return nodes, roads

    print(f"      {len(overlap_edges)} overlap edges found")

    # Step 4: Group roads using Union-Find
    parent: Dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # Path compression
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for longer_rid, shorter_rid in overlap_edges:
        union(longer_rid, shorter_rid)

    # Build groups: root -> set of road IDs
    groups: Dict[int, Set[int]] = {}
    all_grouped_rids = set()
    for longer_rid, shorter_rid in overlap_edges:
        all_grouped_rids.add(longer_rid)
        all_grouped_rids.add(shorter_rid)

    for rid in all_grouped_rids:
        root = find(rid)
        if root not in groups:
            groups[root] = set()
        groups[root].add(rid)

    # Step 5: For each group, keep longest road, mark others for removal
    roads_to_remove: Set[int] = set()

    for root, group_rids in groups.items():
        if len(group_rids) <= 1:
            continue

        # Find the longest road in the group
        primary_rid = max(group_rids, key=lambda rid: road_data[rid]["length"])

        # Mark all others for removal
        for rid in group_rids:
            if rid != primary_rid:
                roads_to_remove.add(rid)

    if not roads_to_remove:
        print("      No duplicate roads to remove")
        return nodes, roads

    # Step 6: Remove marked roads and clean up unused nodes
    original_road_count = len(roads)
    roads = [r for r in roads if r["id"] not in roads_to_remove]

    used_ids: Set[int] = set()
    for road in roads:
        used_ids.update(road["nodes"])

    original_node_count = len(nodes)
    nodes = [n for n in nodes if n["id"] in used_ids]
    removed_nodes = original_node_count - len(nodes)

    print(
        f"      Removed {len(roads_to_remove)} duplicate roads "
        f"({original_road_count} -> {len(roads)})"
    )
    if removed_nodes > 0:
        print(f"      Removed {removed_nodes} unused nodes")

    return nodes, roads


def split_roads_at_intersections(
    roads: List[Dict],
) -> Tuple[List[Dict], Dict[int, List[int]]]:
    """
    Split roads at intersection and overlap points.

    Rules:
    - Roads can only share nodes at start or end points
    - If roads share nodes in the middle, split them at those points
    - Deduplicate shared segments

    Args:
        roads: List of road dictionaries with 'id' and 'nodes' keys

    Returns:
        Tuple of:
        - List of new road segments (with updated IDs and names)
        - Mapping from original road ID to list of new segment IDs
    """
    if not roads:
        return [], {}

    print(f"    Splitting roads at intersections ({len(roads)} roads)...")

    # Step 1: Build node usage map
    # node_id -> list of (road_id, position_index, is_endpoint)
    node_usage: Dict[int, List[Tuple[int, int, bool]]] = {}

    for road in roads:
        road_id = road["id"]
        nodes = road["nodes"]
        if not nodes:
            continue

        for idx, node_id in enumerate(nodes):
            is_endpoint = idx == 0 or idx == len(nodes) - 1

            if node_id not in node_usage:
                node_usage[node_id] = []
            node_usage[node_id].append((road_id, idx, is_endpoint))

    # Step 2: Identify critical nodes (split points)
    # A node is critical if:
    # - It's an endpoint of any road, OR
    # - It appears in more than one road
    critical_nodes: Set[int] = set()

    for node_id, usages in node_usage.items():
        # Check if endpoint of any road
        if any(is_endpoint for _, _, is_endpoint in usages):
            critical_nodes.add(node_id)
        # Check if used by multiple roads
        elif len(set(road_id for road_id, _, _ in usages)) > 1:
            critical_nodes.add(node_id)

    print(f"      Found {len(critical_nodes)} critical nodes (split points)")

    # Step 3: Split each road at critical nodes
    # raw_segments: list of (original_road_id, node_list_tuple)
    raw_segments: List[Tuple[int, Tuple[int, ...]]] = []

    for road in roads:
        road_id = road["id"]
        nodes = road["nodes"]

        if len(nodes) < 2:
            continue

        # Find split indices (positions of critical nodes in this road's middle)
        split_indices = [0]  # Always start from beginning
        for idx in range(
            1, len(nodes) - 1
        ):  # Skip first and last (they're always splits)
            if nodes[idx] in critical_nodes:
                split_indices.append(idx)
        split_indices.append(len(nodes) - 1)  # Always end at last node

        # Remove duplicates and sort
        split_indices = sorted(set(split_indices))

        # Create segments between consecutive split points
        for i in range(len(split_indices) - 1):
            start_idx = split_indices[i]
            end_idx = split_indices[i + 1]

            segment_nodes = tuple(nodes[start_idx : end_idx + 1])
            if len(segment_nodes) >= 2:
                raw_segments.append((road_id, segment_nodes))

    print(f"      Created {len(raw_segments)} raw segments")

    # Step 4: Deduplicate segments
    # Group segments by their node sequence (to find shared segments)
    # Key: node_tuple (or reversed), Value: list of original road IDs
    segment_to_roads: Dict[Tuple[int, ...], Set[int]] = {}

    for original_road_id, segment_nodes in raw_segments:
        # Normalize segment direction (use smaller first node as canonical form)
        # This ensures [1,2,3] and [3,2,1] are treated as same segment
        if segment_nodes[0] > segment_nodes[-1]:
            canonical_nodes = tuple(reversed(segment_nodes))
        else:
            canonical_nodes = segment_nodes

        if canonical_nodes not in segment_to_roads:
            segment_to_roads[canonical_nodes] = set()
        segment_to_roads[canonical_nodes].add(original_road_id)

    # Step 5: Create final segments with proper IDs and names
    new_roads: List[Dict] = []
    new_road_id = 1

    # Map: canonical_nodes -> new_road_id (for building road composition)
    canonical_to_new_id: Dict[Tuple[int, ...], int] = {}

    for canonical_nodes, original_road_ids in segment_to_roads.items():
        is_shared = len(original_road_ids) > 1

        # Generate name
        if is_shared:
            name = f"Road_{new_road_id}_Shared"
        else:
            name = f"Road_{new_road_id}"

        new_road = {
            "id": new_road_id,
            "name": name,
            "nodes": list(canonical_nodes),
            "is_generated": False,
            "ways_num": 2,
            "lanes_num": 1,
            "banking": "",
            "lane_width": "",
            "speed_limit": "",
            "rolling_resistance": "",
            "traction_coefficient": "",
            "offset": 0,
            # Metadata for tracking
            "_original_roads": sorted(original_road_ids),
            "_is_shared": is_shared,
        }
        new_roads.append(new_road)
        canonical_to_new_id[canonical_nodes] = new_road_id
        new_road_id += 1

    # Step 6: Build road composition mapping
    # original_road_id -> list of new segment IDs in order
    road_composition: Dict[int, List[int]] = {}

    for road in roads:
        original_road_id = road["id"]
        nodes = road["nodes"]

        if len(nodes) < 2:
            road_composition[original_road_id] = []
            continue

        # Find split indices again
        split_indices = [0]
        for idx in range(1, len(nodes) - 1):
            if nodes[idx] in critical_nodes:
                split_indices.append(idx)
        split_indices.append(len(nodes) - 1)
        split_indices = sorted(set(split_indices))

        # Build ordered list of segment IDs
        segment_ids = []
        for i in range(len(split_indices) - 1):
            start_idx = split_indices[i]
            end_idx = split_indices[i + 1]

            segment_nodes = tuple(nodes[start_idx : end_idx + 1])
            if len(segment_nodes) < 2:
                continue

            # Find canonical form
            if segment_nodes[0] > segment_nodes[-1]:
                canonical_nodes = tuple(reversed(segment_nodes))
            else:
                canonical_nodes = segment_nodes

            if canonical_nodes in canonical_to_new_id:
                segment_ids.append(canonical_to_new_id[canonical_nodes])

        road_composition[original_road_id] = segment_ids

    # Count shared segments
    shared_count = sum(1 for r in new_roads if r.get("_is_shared", False))
    print(f"      Final: {len(new_roads)} segments ({shared_count} shared)")

    return new_roads, road_composition


def update_routes_with_split_roads(
    routes: List[Dict],
    road_composition: Dict[int, List[int]],
) -> List[Dict]:
    """
    Update route definitions to use split road segments.

    Args:
        routes: List of route dictionaries with 'haul' and 'return' keys
        road_composition: Mapping from original road ID to list of new segment IDs

    Returns:
        Updated routes with expanded road references
    """
    if not routes:
        return routes

    updated_routes = []
    for route in routes:
        new_route = route.copy()

        # Update haul path
        if "haul" in route and route["haul"]:
            new_haul = []
            for road_id in route["haul"]:
                if road_id in road_composition:
                    new_haul.extend(road_composition[road_id])
                else:
                    new_haul.append(road_id)
            new_route["haul"] = new_haul

        # Update return path
        if "return" in route and route["return"]:
            new_return = []
            for road_id in route["return"]:
                if road_id in road_composition:
                    new_return.extend(road_composition[road_id])
                else:
                    new_return.append(road_id)
            new_route["return"] = new_return

        updated_routes.append(new_route)

    return updated_routes


def find_connected_components(roads: List[Dict]) -> List[Set[int]]:
    """
    Find connected components in road network using BFS.

    Args:
        roads: List of road dictionaries with 'nodes' field

    Returns:
        List of sets, each set contains node_ids belonging to same component
    """
    # Build adjacency list (undirected graph)
    graph = defaultdict(set)
    for road in roads:
        road_nodes = road.get("nodes", [])
        for i in range(len(road_nodes) - 1):
            graph[road_nodes[i]].add(road_nodes[i + 1])
            graph[road_nodes[i + 1]].add(road_nodes[i])

    # BFS to find connected components. Iterate node ids and neighbours in sorted
    # order so component discovery is deterministic (graph is built from sets, whose
    # iteration order is not stable run-to-run).
    all_node_ids = set(graph.keys())
    visited = set()
    components = []

    for node_id in sorted(all_node_ids):
        if node_id not in visited:
            component = set()
            queue = deque([node_id])
            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in sorted(graph[current]):
                    if neighbor not in visited:
                        queue.append(neighbor)
            components.append(component)

    # Stable component order (each is a set; order them by smallest node id).
    components.sort(key=lambda s: min(s) if s else -1)
    return components
