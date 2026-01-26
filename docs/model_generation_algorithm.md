# Model Generation Algorithm

## Overview

This document provides comprehensive technical documentation of the model generation algorithm used to create road network models from AMT (Autonomous Mining Truck) telemetry data. The generated model is used for discrete event simulation (DES) and animation playback in the Digital Twin application.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Flow Pipeline](#2-data-flow-pipeline)
3. [Core Algorithms](#3-core-algorithms)
4. [Data Structures](#4-data-structures)
5. [Configuration Parameters](#5-configuration-parameters)
6. [Business Rules](#6-business-rules)
7. [Performance Characteristics](#7-performance-characteristics)
8. [Usage Examples](#8-usage-examples)

---

## 1. Architecture Overview

### 1.1 High-Level Pipeline

The generator is implemented as a package `backend/scripts/simgen/` with a thin facade at `backend/scripts/simulation_generator.py` that re-exports from it. Each step lives in a dedicated module (see §1.2).

```
Telemetry Data (Database or Import)
    ↓
┌─────────────────────────────────────────────────────────┐
│     simulation_generator.py  (facade + process_site)     │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Step 1: fetch_telemetry_data()          [db.py]   │  │
│  │   - Query database for GPS points                 │  │
│  │   - Apply sampling interval                       │  │
│  │   - Sort by machine, cycle, segment, interval     │  │
│  └───────────────────────────────────────────────────┘  │
│                          ↓                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Step 2: create_roads_from_trajectories() [facade] │  │
│  │   - Group by machine                              │  │
│  │   - Douglas-Peucker simplification                │  │
│  │   - Node deduplication with tolerance             │  │
│  │   - Output: nodes[], roads[]                      │  │
│  └───────────────────────────────────────────────────┘  │
│                          ↓                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Step 3: split_roads_at_intersections() [roads.py] │  │
│  │   - Find critical nodes (intersections/overlaps)  │  │
│  │   - Split roads at critical nodes                 │  │
│  │   - Deduplicate shared segments                   │  │
│  │   - Output: split_roads[], road_composition{}     │  │
│  └───────────────────────────────────────────────────┘  │
│                          ↓                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Step 4: detect_zones()              [zones.py]    │  │
│  │   - Grid-based stop point clustering              │  │
│  │   - Transition-count classification               │  │
│  │   - Road endpoint linking                         │  │
│  │   - Output: load_zones[], dump_zones[]            │  │
│  └───────────────────────────────────────────────────┘  │
│                          ↓                               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Step 5: create_model()              [model.py]    │  │
│  │   - Assemble complete model structure             │  │
│  │   - Add default settings                          │  │
│  │   - Calculate camera position                     │  │
│  │   - Output: model.json                            │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
    ↓
model_{site_name}.json
```

### 1.2 Component Diagram

The generator is decomposed into a package (`backend/scripts/simgen/`) with the following modules:

| Module | Responsibilities |
|--------|-----------------|
| `constants.py` | Named constants (thresholds, defaults) |
| `geometry.py` | Geometric helpers (Douglas-Peucker, polyline length, overlap ratio) |
| `loaders.py` | File loading: machines, materials, zone assignments |
| `db.py` | Database/DuckDB queries |
| `roads.py` | `merge_overlapping_roads`, `split_roads_at_intersections`, `find_connected_components` |
| `zones.py` | `detect_zones`, `convert_reader_zones_to_model` |
| `routes.py` | `create_routes`, `update_zone_settings_for_routes` |
| `operations.py` | `create_operations_structure`, trip analysis, material schedule building |
| `model.py` | `create_model`, `create_service_stations_for_haulers` |
| `specs.py` | DES spec generation |
| `des.py` | DES inputs / events ledger |

`simulation_generator.py` is a **thin facade** — it re-exports from each module via `from backend.scripts.simgen.X import *` and hosts `process_site()` plus `create_roads_from_trajectories()` (kept in the facade by design; see inline note at line 71).

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Model Generation System                            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐  │
│  │ Data Source │   │Road Builder │   │Road Splitter│   │Zone Detector│  │
│  │  [db.py]    │   │  [facade]   │   │ [roads.py]  │   │ [zones.py]  │  │
│  │ • Database  │──▶│ • Trajectory│──▶│ • Find      │──▶│ • Grid      │  │
│  │ • Import    │   │   Grouping  │   │   Critical  │   │   Clustering│  │
│  │   File      │   │ • Douglas-  │   │   Nodes     │   │ • Transition│  │
│  │             │   │   Peucker   │   │ • Split at  │   │   Counting  │  │
│  │             │   │ • Node      │   │   Intersect │   │ • Road Link │  │
│  │             │   │   Dedup     │   │ • Dedup     │   │             │  │
│  │             │   │             │   │   Shared    │   │             │  │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘  │
│         │                 │                 │                 │          │
│         └─────────────────┴─────────────────┴─────────────────┘          │
│                                    ▼                                      │
│                      ┌─────────────────────────┐                         │
│                      │    Model Assembler      │                         │
│                      │      [model.py]         │                         │
│                      │   • Structure Builder   │                         │
│                      │   • Settings Merger     │                         │
│                      │   • Camera Calculator   │                         │
│                      └─────────────────────────┘                         │
│                                    │                                      │
│                                    ▼                                      │
│                             model.json                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Pipeline

### 2.1 Input Data Format

Telemetry data is fetched as tuples with the following structure:

| Index | Field | Type | Unit | Description |
|-------|-------|------|------|-------------|
| 0 | machine_id | int | - | Machine unique identifier |
| 1 | segment_id | int | - | GPS timestamp (segment identifier) |
| 2 | cycle_id | int | - | Cycle identifier |
| 3 | interval | int | - | Interval index within segment |
| 4 | pathEasting | int | mm | X coordinate (East) |
| 5 | pathNorthing | int | mm | Y coordinate (North) |
| 6 | pathElevation | int | mm | Z coordinate (Elevation) |
| 7 | expectedSpeed | int | kph | Expected speed |
| 8 | actualSpeed | int | kph | Actual speed |
| 9 | pathBank | int | deg | Road banking angle |
| 10 | pathHeading | int | deg | Direction of travel |
| 11 | leftWidth | int | cm | Left lane width |
| 12 | rightWidth | int | cm | Right lane width |
| 13 | payloadPercent | int | % | Payload percentage (0-100) |

### 2.2 Coordinate Conversion

```python
def convert_coordinates(path_easting, path_northing, path_elevation):
    """Convert database coordinates (mm) to meters."""
    return (
        round(path_easting / 1000.0, 3),
        round(path_northing / 1000.0, 3),
        round(path_elevation / 1000.0, 3),
    )
```

### 2.3 Data Sorting

Data is sorted by `(machine_id, cycle_id, segment_id, interval)` to ensure correct temporal ordering for trajectory reconstruction.

---

## 3. Core Algorithms

### 3.1 Road Network Generation

**Function**: `create_roads_from_trajectories()` — `backend/scripts/simulation_generator.py` (facade; kept there by design — see inline note at line 71)

**Purpose**: Create road network from actual vehicle trajectories, ensuring nodes and roads follow the actual path of vehicles for accurate animation playback.

#### Algorithm Steps

##### Step 1: Group Telemetry by Machine

```python
machine_trajectories = {}
for row in telemetry_data:
    machine_id = row[0]
    coord = convert_coordinates(row[4], row[5], row[6])

    if machine_id not in machine_trajectories:
        machine_trajectories[machine_id] = []
    machine_trajectories[machine_id].append(coord)
```

##### Step 2: Douglas-Peucker Path Simplification

The Douglas-Peucker algorithm reduces the number of points in a path while preserving its shape.

```
Input Points:    P1 ─ P2 ─ P3 ─ P4 ─ P5 ─ P6 ─ P7
                  \                           /
                   \─────── max distance ────/
                              ↓
Simplified:       P1 ─────── P4 ─────────── P7
```

**Algorithm**:

```python
def douglas_peucker(points, epsilon):
    """
    Recursive path simplification algorithm.

    Args:
        points: List of (x, y, z) coordinates
        epsilon: Maximum perpendicular distance threshold (meters)

    Returns:
        Simplified list of points
    """
    if len(points) <= 2:
        return points

    # Find point with maximum perpendicular distance
    start, end = points[0], points[-1]
    max_dist = 0
    max_idx = 0

    for i in range(1, len(points) - 1):
        dist = perpendicular_distance(points[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    # If max distance exceeds epsilon, recursively simplify
    if max_dist > epsilon:
        left = douglas_peucker(points[:max_idx + 1], epsilon)
        right = douglas_peucker(points[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [start, end]
```

**Perpendicular Distance Calculation**:

```python
def perpendicular_distance(point, line_start, line_end):
    """Calculate perpendicular distance from point to line (2D)."""
    x0, y0 = point[0], point[1]
    x1, y1 = line_start[0], line_start[1]
    x2, y2 = line_end[0], line_end[1]

    line_len = sqrt((x2 - x1)² + (y2 - y1)²)
    if line_len == 0:
        return sqrt((x0 - x1)² + (y0 - y1)²)

    # Area of triangle formula
    return abs((y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1) / line_len
```

##### Step 3: Minimum Distance Filtering

After Douglas-Peucker, apply minimum segment distance filter:

```python
min_segment_distance = 15.0  # meters

filtered_points = [simplified[0]]
for point in simplified[1:]:
    if calculate_distance(filtered_points[-1], point) >= min_segment_distance:
        filtered_points.append(point)

# Ensure last point is included
if filtered_points[-1] != simplified[-1]:
    if calculate_distance(filtered_points[-1], simplified[-1]) >= min_segment_distance / 2:
        filtered_points.append(simplified[-1])
```

##### Step 4: Node Deduplication with Tolerance

Nodes within a tolerance radius are merged to avoid duplicates:

```python
def get_or_create_node(coord, tolerance=5.0):
    """
    Get existing node or create new one.

    Args:
        coord: (x, y, z) coordinate in meters
        tolerance: Maximum distance to consider nodes as same (meters)

    Returns:
        Node ID (existing or newly created)
    """
    x, y, z = coord

    # Check if node already exists nearby
    for (nx, ny), nid in coord_to_node_id.items():
        if sqrt((x - nx)² + (y - ny)²) < tolerance:
            return nid  # Reuse existing node

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
    coord_to_node_id[(x, y)] = node_id
    node_id += 1
    return new_node["id"]
```

##### Step 5: Road Creation

For each machine trajectory, create a road connecting the nodes:

```python
road_node_ids = []
for point in filtered_points:
    nid = get_or_create_node(point)
    # Avoid consecutive duplicates
    if not road_node_ids or road_node_ids[-1] != nid:
        road_node_ids.append(nid)

if len(road_node_ids) >= 2:
    road = {
        "id": road_id,
        "name": f"Road_{road_id}",
        "nodes": road_node_ids,  # Sequential order preserved
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
    roads.append(road)
```

##### Step 6: Cleanup Unused Nodes

Remove nodes that are not referenced by any road:

```python
used_node_ids = set()
for road in roads:
    used_node_ids.update(road["nodes"])

all_nodes = [node for node in all_nodes if node["id"] in used_node_ids]
```

#### Visual Representation

```
Raw Trajectory (1000 points):
[P1]·[P2]·[P3]·[P4]·[P5]·[P6]·[P7]·[P8]·[P9]·[P10]...
     ↓ Douglas-Peucker (epsilon=5.0m)

Simplified (50 points):
[P1]─────[P15]─────[P30]─────[P45]─────[P60]...
     ↓ Min Distance Filter (15.0m)

Filtered (20 points):
[P1]───────────[P30]───────────[P60]...
     ↓ Node Deduplication (tolerance=5.0m)

Final Road:
[N1]───────────[N2]───────────[N3]...
  │             │              │
  └─────────────┴──────────────┘
        Road { nodes: [N1, N2, N3] }
```

---

### 3.2 Road Intersection Splitting

**Function**: `split_roads_at_intersections()` — `backend/scripts/simgen/roads.py`

**Purpose**: Split roads at intersection and overlap points to ensure roads only share nodes at endpoints. This is required for proper route navigation and simulation.

#### Problem Statement

Roads generated from multiple vehicle trajectories may:
1. **Intersect**: Cross each other at a common node in the middle
2. **Overlap**: Share a common path segment

```
Before Splitting:
┌────────────────────────────────────────────────────────────┐
│                                                             │
│  Road A: [1]─[2]─[3]─[4]─[5]      Intersection at node 3   │
│                   │                                         │
│  Road B: [6]─[7]─[3]─[8]─[9]                               │
│                                                             │
│  Road C: [1]─[2]─[3]─[10]─[11]   Overlap at nodes 1,2,3    │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

#### Algorithm Steps

##### Step 1: Build Node Usage Map

Track which roads use each node and at what position:

```python
node_usage = {}  # node_id -> list of (road_id, position_index, is_endpoint)

for road in roads:
    for idx, node_id in enumerate(road["nodes"]):
        is_endpoint = (idx == 0 or idx == len(nodes) - 1)
        node_usage[node_id].append((road_id, idx, is_endpoint))
```

##### Step 2: Identify Critical Nodes

A node is **critical** (split point) if:
- It's an endpoint of any road, OR
- It appears in more than one road

```python
critical_nodes = set()

for node_id, usages in node_usage.items():
    # Endpoint of any road
    if any(is_endpoint for _, _, is_endpoint in usages):
        critical_nodes.add(node_id)
    # Used by multiple roads
    elif len(set(road_id for road_id, _, _ in usages)) > 1:
        critical_nodes.add(node_id)
```

##### Step 3: Split Roads at Critical Nodes

For each road, split at critical nodes that appear in its middle:

```python
for road in roads:
    nodes = road["nodes"]

    # Find split indices
    split_indices = [0]  # Start
    for idx in range(1, len(nodes) - 1):
        if nodes[idx] in critical_nodes:
            split_indices.append(idx)
    split_indices.append(len(nodes) - 1)  # End

    # Create segments between consecutive split points
    for i in range(len(split_indices) - 1):
        segment = nodes[split_indices[i]:split_indices[i+1] + 1]
        raw_segments.append((road_id, segment))
```

##### Step 4: Deduplicate Shared Segments

Segments with identical node sequences are merged:

```python
segment_to_roads = {}  # canonical_nodes -> set of original_road_ids

for original_road_id, segment_nodes in raw_segments:
    # Normalize direction (smaller first node as canonical)
    if segment_nodes[0] > segment_nodes[-1]:
        canonical = tuple(reversed(segment_nodes))
    else:
        canonical = tuple(segment_nodes)

    segment_to_roads[canonical].add(original_road_id)
```

##### Step 5: Create Final Segments

```python
for canonical_nodes, original_road_ids in segment_to_roads.items():
    is_shared = len(original_road_ids) > 1

    new_road = {
        "id": new_road_id,
        "name": f"Road_{new_road_id}_Shared" if is_shared else f"Road_{new_road_id}",
        "nodes": list(canonical_nodes),
        "_original_roads": sorted(original_road_ids),
        "_is_shared": is_shared,
        ...
    }
```

##### Step 6: Build Road Composition Mapping

Map original roads to their new segment IDs:

```python
road_composition = {}  # original_road_id -> [new_segment_ids]

for road in original_roads:
    segment_ids = []
    for segment in split_segments_of(road):
        segment_ids.append(find_new_id(segment))
    road_composition[road["id"]] = segment_ids
```

#### Visual Representation

**Example 1: Intersection**

```
Input:
  Road A: [1, 2, 3, 4, 5]
  Road B: [6, 7, 3, 8, 9]

Critical Nodes: {1, 3, 5, 6, 9}  (endpoints + intersection)

Split Result:
  Road_1: [1, 2, 3]  ← from Road A
  Road_2: [3, 4, 5]  ← from Road A
  Road_3: [6, 7, 3]  ← from Road B
  Road_4: [3, 8, 9]  ← from Road B

Composition:
  Road A → [Road_1, Road_2]
  Road B → [Road_3, Road_4]
```

**Example 2: Overlap**

```
Input:
  Road A: [1, 2, 3, 4, 5]
  Road B: [1, 2, 3, 6, 7]
  Road C: [8, 2, 3, 10]

Critical Nodes: {1, 2, 3, 5, 7, 8, 10}  (endpoints + multi-road usage)

Split Result:
  Road_1_Shared: [1, 2]   ← used by A, B
  Road_2_Shared: [2, 3]   ← used by A, B, C
  Road_3: [3, 4, 5]       ← used by A only
  Road_4: [3, 6, 7]       ← used by B only
  Road_5: [8, 2]          ← used by C only
  Road_6: [3, 10]         ← used by C only

Composition:
  Road A → [Road_1, Road_2, Road_3]
  Road B → [Road_1, Road_2, Road_4]
  Road C → [Road_5, Road_2, Road_6]
```

#### Road Structure After Splitting

```json
{
  "id": 1,
  "name": "Road_1_Shared",
  "nodes": [1, 2],
  "is_generated": false,
  "ways_num": 2,
  "lanes_num": 1,
  "_original_roads": [1, 2],
  "_is_shared": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `_original_roads` | [int] | List of original road IDs that use this segment |
| `_is_shared` | bool | True if segment is shared by multiple original roads |

---

### 3.3 Zone Detection

**Function**: `detect_zones()` — `backend/scripts/simgen/zones.py`

**Purpose**: Identify load and dump zones from stopped vehicle points using grid-based clustering and payload-transition analysis.

#### Algorithm Steps

##### Step 1: Build Grid from Stop Points

Only consider points where vehicle speed ≤ 5 km/h:

```python
grid = {}  # key: (grid_x, grid_y), value: {points, payloads, elevations}

for row in telemetry_data:
    actual_speed = row[8]
    payload = row[13]

    if actual_speed <= 5:  # Vehicle stopped or very slow
        x, y, z = convert_coordinates(row[4], row[5], row[6])

        # Snap to grid
        grid_x = round(x / grid_size) * grid_size
        grid_y = round(y / grid_size) * grid_size
        key = (grid_x, grid_y)

        if key not in grid:
            grid[key] = {'points': [], 'payloads': [], 'elevations': []}

        grid[key]['points'].append((x, y, z))
        grid[key]['elevations'].append(z)

        if 0 <= payload <= 100:
            grid[key]['payloads'].append(payload)
```

##### Step 2: Filter by Minimum Stop Count

Only grid cells with sufficient stop points are considered:

```python
min_stop_count = 20  # Minimum stops required

filtered_cells = {
    key: data
    for key, data in grid.items()
    if len(data['points']) >= min_stop_count
}
```

##### Step 3: Classify Zones by Payload Transitions

Classification uses **payload transition counting** (M4) rather than a simple mean-payload threshold. Each machine's telemetry is walked in time order; when payload crosses `LOADED_PAYLOAD_THRESHOLD = 50%` (constants.py), the grid cell at that coordinate receives a `load` or `dump` tally:

```python
LOADED_PAYLOAD_THRESHOLD = 50  # constants.py

# For each machine, walk telemetry in time order:
if not prev_loaded and is_loaded:
    transition_counts[cell_key]["load"] += 1   # empty→loaded = load event
elif prev_loaded and not is_loaded:
    transition_counts[cell_key]["dump"] += 1   # loaded→empty = dump event

# Classification per cell (zones.py ~line 300):
counts = transition_counts.get(cell_key, {"load": 0, "dump": 0})
if counts["load"] != counts["dump"]:
    is_load_zone = counts["load"] > counts["dump"]
else:
    # Fallback to mean payload only when no transitions observed
    is_load_zone = avg_payload <= LOADED_PAYLOAD_THRESHOLD
```

This approach correctly handles cells where trucks park after loading (high mean payload despite being a load zone). The mean-payload fallback is only used when no transitions are observed for a cell.

**Classification Logic**:

```
┌─────────────────────────────────────────────────────────────┐
│              Payload Transition Counting (primary)           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  more load transitions  →  LOAD ZONE                        │
│  more dump transitions  →  DUMP ZONE                        │
│  equal transitions      →  fallback: avg_payload < 50%?     │
│                                       yes → LOAD, no → DUMP  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

##### Step 4: Link Zones to Road Network

Each zone must be connected to the nearest road endpoint:

```python
MAX_ZONE_ROAD_DISTANCE = 100  # meters

def find_nearest_road_endpoint(zone_x, zone_y):
    """Find nearest road start/end node to zone center."""
    min_dist = float('inf')
    nearest = None

    for road in roads:
        start_node = node_lookup[road["nodes"][0]]
        end_node = node_lookup[road["nodes"][-1]]

        for node, node_id in [(start_node, road["nodes"][0]),
                               (end_node, road["nodes"][-1])]:
            dist = sqrt((zone_x - node["coords"][0])² +
                       (zone_y - node["coords"][1])²)
            if dist < min_dist:
                min_dist = dist
                nearest = {
                    "road_id": road["id"],
                    "node_id": node_id,
                    "distance": dist
                }

    return nearest if nearest and nearest["distance"] <= MAX_ZONE_ROAD_DISTANCE else None
```

##### Step 5: Create Zone Objects

```python
zone_settings = {
    "zonetype": "standard",
    "n_spots": 1,
    "n_entrances": 1,
    "roadlength": 100,
    "width": 50,
    "access_distance": 40,
    "angular_spread": 80,
    "clearance_radius": 80,
    "speed_limit": "",
    "rolling_resistance": "",
    "reverse_speed_limit": "",
    "flip": False,
    "dtheta": 0,
    "queing": False,
    "inroad_ids": [nearest["road_id"]],
    "outroad_ids": [nearest["road_id"]],
    "innode_ids": [nearest["node_id"]],
    "outnode_ids": [nearest["node_id"]],
}

# Load zone (zones.py ~line 329):
zone = {
    "id": load_id,
    "name": f"Load zone {load_id}",   # auto-incrementing integer ids
    "keys": "load_zones",
    "is_generated": True,
    "connector_zone_data": [],
    "settings": zone_settings,
    "detected_location": {"x": grid_x, "y": grid_y, "z": avg_z},
}

# Dump zone (zones.py ~line 343):
zone = {
    "id": dump_id,
    "name": f"Dump zone {dump_id}",   # separate counter from load_id
    "is_generated": True,
    "connector_zone_data": [],
    "settings": zone_settings,
    "detected_location": {"x": grid_x, "y": grid_y, "z": avg_z},
}
```

#### Visual Representation

```
GPS Stop Points (speed ≤ 5 km/h):
  ┌─────────────────────────────────────────────────┐
  │    ·  ·  ·           ·  ·  ·  ·                 │
  │   ·  ·  ·  ·                    ·  ·           │
  │    ·  ·  ·           ·  ·  ·  ·  ·             │
  │                      ·  ·  ·  ·                 │
  │   Low Payload        High Payload              │
  │   (avg 15%)          (avg 85%)                 │
  └─────────────────────────────────────────────────┘
         ↓ Grid Clustering (10m cells)

  ┌─────────────────────────────────────────────────┐
  │   ┌───────┐          ┌───────┐                 │
  │   │ LOAD  │          │ DUMP  │                 │
  │   │ ZONE  │          │ ZONE  │                 │
  │   │  LZ-1 │          │  DZ-1 │                 │
  │   └───────┘          └───────┘                 │
  └─────────────────────────────────────────────────┘
```

---

### 3.4 Model Assembly

**Function**: `create_model()` — `backend/scripts/simgen/model.py`

**Purpose**: Assemble complete model structure with nodes, roads, zones, haulers, loaders, routes, operations, and default settings.

#### Model Structure

```python
# model.py — create_model signature
def create_model(
    nodes, roads,
    load_zones=None, dump_zones=None,
    version="2.0.51",
    machines=None,            # machine info from DB/import
    machines_list=None,       # machine specs from machines.json
    machines_with_events=None,# filter: only machines that have events
    telemetry_data=None,      # raw telemetry (for hauler initial positions + trip analysis)
    coordinates_in_meters=False,
    material=DEFAULT_MATERIAL,         # "copper_ore"
    density=DEFAULT_MATERIAL_DENSITY,  # 1960.19 kg/m³ fallback
    zone_material_map=None,   # optional per-load-zone (material, density) overrides
):
    model = {
        # Metadata
        "version": version,
        "map_id": -1,
        "map_translate": {
            "total_northing": 0,
            "total_easting": 0,
            "total_elevation": 0,
            "total_angle": 0
        },

        # Road Network
        "nodes": nodes,
        "roads": roads,

        # Zones
        "load_zones": load_zones,
        "dump_zones": dump_zones,

        # Settings (see full structure below)
        "settings": {...},

        # Machine list populated from machines + machines.json
        "machine_list": {"haulers": [...], "loaders": [...]},
        "parameters": [],
        "trolleys": [],
        "chargers": [],         # fuel zones, auto-created at service station nodes
        "service_stations": [], # created at network center nodes
        "routes": routes,       # created by routes.py create_routes()
        "haulers": [...],       # one per machine_id, initial_position=2 (service zone)
        "loaders": [...],       # one per load_zone
        "simulates": [],
        "esses": [],
        "batteries": [],
        "crushers": [],

        # Operations (material schedules) — created by operations.py
        "operations": create_operations_structure(...),

        # Camera
        "cameraPosition": {...},
        "controlTarget": {...},
    }

    return model
```

#### Camera Position Calculation

Camera is positioned to view the entire road network:

```python
if nodes:
    eastings = [n["coords"][0] for n in nodes]
    northings = [n["coords"][1] for n in nodes]
    elevations = [n["coords"][2] for n in nodes]

    # Calculate center point
    center_x = (min(eastings) + max(eastings)) / 2
    center_y = (min(northings) + max(northings)) / 2
    center_z = (min(elevations) + max(elevations)) / 2

    # Calculate span for camera height
    span = max(max(eastings) - min(eastings),
               max(northings) - min(northings))

    model["cameraPosition"] = {
        "x": center_x,
        "y": center_z + span,  # Above the network
        "z": center_y
    }
    model["controlTarget"] = {
        "x": center_x,
        "y": center_z,
        "z": center_y
    }
```

---

## 4. Data Structures

### 4.1 Node Structure

```json
{
  "id": 1,
  "name": "Node_1",
  "coords": [1357.019, -936.497, -91.181],
  "speed_limit": 40.0,
  "rolling_resistance": 2.5,
  "banking": 0,
  "curvature": "",
  "lane_width": 14,
  "traction": 0.6
}
```

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `id` | int | - | Unique node identifier |
| `name` | string | - | Display name |
| `coords` | [x, y, z] | meters | 3D coordinates |
| `speed_limit` | number/string | kph | Speed limit at node |
| `rolling_resistance` | number/string | % | Rolling resistance |
| `banking` | number/string | degrees | Road banking angle |
| `curvature` | number/string | 1/m | Road curvature |
| `lane_width` | number/string | meters | Lane width |
| `traction` | number/string | - | Traction coefficient |

### 4.2 Road Structure

```json
{
  "id": 1,
  "name": "Road_1",
  "nodes": [1, 2, 3, 4, 5],
  "is_generated": false,
  "ways_num": 2,
  "lanes_num": 1,
  "banking": "",
  "lane_width": "",
  "speed_limit": "",
  "rolling_resistance": "",
  "traction_coefficient": "",
  "offset": 0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Unique road identifier |
| `name` | string | Display name |
| `nodes` | [int] | **Ordered** list of node IDs (CRITICAL) |
| `is_generated` | bool | Auto-generated flag |
| `ways_num` | int | Number of ways (1=one-way, 2=two-way) |
| `lanes_num` | int | Number of lanes per way |
| `offset` | number | Lateral offset from centerline (meters) |

### 4.3 Zone Structure

```json
{
  "id": 1,
  "name": "Load zone 1",
  "is_generated": true,
  "connector_zone_data": [],
  "settings": {
    "zonetype": "standard",
    "n_spots": 1,
    "n_entrances": 1,
    "roadlength": 100,
    "width": 50,
    "access_distance": 40,
    "angular_spread": 80,
    "clearance_radius": 80,
    "speed_limit": "",
    "rolling_resistance": "",
    "reverse_speed_limit": "",
    "flip": false,
    "dtheta": 0,
    "queing": false,
    "inroad_ids": [1],
    "outroad_ids": [1],
    "innode_ids": [10],
    "outnode_ids": [12]
  },
  "detected_location": {
    "x": 150.5,
    "y": -200.3,
    "z": -50.0
  }
}
```

---

## 5. Configuration Parameters

### 5.1 Road Detection Parameters

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `simplify_epsilon` | 5.0 | meters | Douglas-Peucker threshold |
| `min_segment_distance` | 15.0 | meters | Minimum distance between nodes |
| `node_tolerance` | 5.0 | meters | Radius for node deduplication |

### 5.2 Zone Detection Parameters

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `grid_size` | 10.0 | meters | Grid cell size for clustering |
| `min_stop_count` | 20 | points | Minimum stops to form zone |
| `max_zone_distance` | 100 | meters | Max distance from zone to road endpoint (`ZONE_TO_ROAD_MAX_DIST_M`; 200m for Reader.py conversion) |
| `loaded_payload_threshold` | 50 | % | Boundary used for transition detection and mean-payload fallback (`LOADED_PAYLOAD_THRESHOLD`) |

### 5.3 Data Fetching Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | 100000 | Maximum telemetry records |
| `sample_interval` | 5 | Sample every Nth record |

### 5.4 Configuration File

```json
{
  "site": "BhpEscondida",
  "output_dir": "output",
  "data_fetching": {
    "limit": 100000,
    "sample_interval": 5
  },
  "road_detection": {
    "grid_size": 5.0,
    "min_density": 3,
    "simplify_epsilon": 5.0
  },
  "zone_detection": {
    "grid_size": 10.0,
    "min_stop_count": 20
  },
  "simulation": {
    "sim_time": 480
  }
}
```

---

## 6. Business Rules

### 6.1 Road Network Rules

| Rule | Description | Rationale |
|------|-------------|-----------|
| **Sequential Nodes** | Road.nodes must be in traversal order | Required for animation playback |
| **No Consecutive Duplicates** | [1, 1, 2] → [1, 2] | Prevents stuck animation |
| **Minimum 2 Nodes** | Roads with < 2 nodes are discarded | Invalid road segment |
| **Node Reuse** | Nodes within 5m are merged | Reduces redundancy |
| **Endpoint-Only Sharing** | Roads can only share nodes at start/end | Enables proper route navigation |
| **Intersection Splitting** | Roads crossing in middle are split | Prevents ambiguous paths |
| **Shared Segment Naming** | Shared roads named with "_Shared" suffix | Visual identification |

### 6.2 Zone Rules

| Rule | Description | Rationale |
|------|-------------|-----------|
| **Road Connection Required** | Zones must link to road endpoint | Navigation requirement |
| **Minimum Stop Count** | ≥20 stops required | Filter noise |
| **Transition-Count Classification** | More load transitions → Load zone; more dump transitions → Dump zone; tie → mean payload < 50% = Load | Correctly handles post-load high-payload stops (M4 fix) |
| **Maximum Distance** | Zone must be within 100m of road (grid-based detect_zones); 200m for Reader.py conversion | Realistic connectivity |

### 6.3 Coordinate Rules

| Source | Unit | Conversion |
|--------|------|------------|
| Database | millimeters | ÷ 1000 → meters |
| Import File | meters | No conversion |
| Model Output | meters | Final format |

---

## 7. Performance Characteristics

### 7.1 Time Complexity

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Douglas-Peucker | O(n log n) | Recursive bisection |
| Node Deduplication | O(n²) | Tolerance check against all |
| Grid Clustering | O(n) | Single pass |
| Zone-Road Linking | O(z × r) | z=zones, r=roads |

### 7.2 Space Complexity

| Data Structure | Size Estimate |
|----------------|---------------|
| Raw Telemetry (100k points) | ~15 MB |
| Nodes (1000 nodes) | ~100 KB |
| Roads (100 roads) | ~50 KB |
| Final Model | ~500 KB - 2 MB |

### 7.3 Typical Processing Times

| Dataset Size | Processing Time |
|--------------|-----------------|
| 10,000 points | ~5 seconds |
| 100,000 points | ~30-60 seconds |
| 500,000 points | ~3-5 minutes |

---

## 8. Usage Examples

### 8.1 Command Line Usage

```bash
# Generate model for specific site
python scripts/simulation_generator.py --site "BhpEscondida"

# Use custom configuration
python scripts/simulation_generator.py --config custom_config.json

# List available sites
python scripts/simulation_generator.py --list-sites

# Process all sites
python scripts/simulation_generator.py --all-sites
```

### 8.2 Programmatic Usage

All symbols are importable from either the facade or their owning simgen module:

```python
# From the facade (re-exports everything via `from simgen.X import *`)
from backend.scripts.simulation_generator import (
    fetch_telemetry_data,            # db.py
    create_roads_from_trajectories,  # facade (simulation_generator.py)
    split_roads_at_intersections,    # roads.py
    detect_zones,                    # zones.py
    create_model,                    # model.py
)

# Or directly from the simgen package:
from backend.scripts.simgen.roads import split_roads_at_intersections
from backend.scripts.simgen.zones import detect_zones
from backend.scripts.simgen.model import create_model

# 1. Fetch telemetry data
telemetry = fetch_telemetry_data(cursor, machine_ids, limit=100000)

# 2. Create road network
nodes, roads = create_roads_from_trajectories(
    telemetry,
    simplify_epsilon=5.0,
    min_segment_distance=15.0,
)

# 3. Split roads at intersections
roads, road_composition = split_roads_at_intersections(roads)
# road_composition: {original_road_id: [new_segment_ids]}

# 4. Detect zones
load_zones, dump_zones = detect_zones(
    telemetry, nodes, roads,
    grid_size=10.0,
    min_stop_count=20,
)

# 5. Assemble model
model = create_model(nodes, roads, load_zones, dump_zones)

# 6. Save to file
with open("model.json", "w") as f:
    json.dump(model, f, indent=2)
```

### 8.3 Output Files

| File | Description |
|------|-------------|
| `model_{site}.json` | Road network model |
| `des_inputs_{site}.json` | Simulation configuration |
| `simulation_ledger_{site}.json` | Events for animation |

---

## Appendix A: Legacy Road Detection

The system includes a legacy method `detect_road_network()` that uses grid-based density analysis instead of trajectory following.

### Comparison

| Aspect | create_roads_from_trajectories | detect_road_network |
|--------|-------------------------------|---------------------|
| Accuracy | High (follows actual paths) | Medium |
| Node Order | Guaranteed sequential | May be disordered |
| Animation | Optimal | May have issues |
| Recommended | ✅ Yes | Legacy only |

### Legacy Algorithm

```python
def detect_road_network(all_points, grid_size=5.0, min_density=3):
    # 1. Build density grid
    grid = {}
    for point in all_points:
        key = (int(point[0] / grid_size), int(point[1] / grid_size))
        grid[key].append(point)

    # 2. Filter by density
    road_cells = {k: v for k, v in grid.items() if len(v) >= min_density}

    # 3. Find connected components (BFS)
    components = bfs_connected_components(road_cells)

    # 4. Order points using nearest neighbor
    for component in components:
        ordered_path = order_path_points(component)

    # 5. Simplify with Douglas-Peucker
    simplified = douglas_peucker(ordered_path, epsilon)

    return nodes, roads
```

---

## Appendix B: Zone Types

| Type | Description | Use Case |
|------|-------------|----------|
| `standard` | Standard loading/dumping | Default |
| `uturn` | U-turn configuration | Tight spaces |
| `turnaround` | Turnaround configuration | Dead ends |
| `drivethrough` | Drive-through configuration | High throughput |

---

*Document Version: 1.2*
*Last Updated: 2026-06-26*
*Source: backend/scripts/simgen/ package (model.py, zones.py, roads.py, routes.py, operations.py, constants.py) + simulation_generator.py facade*

---

## Changelog

### Version 1.2 (2026-06-26)
- Updated architecture (§1.1, §1.2) to reflect the `backend/scripts/simgen/` package decomposition; attributed each step to its owning module
- Updated §3.3 (Zone Detection) to document M4 transition-count classification algorithm; replaced stale 30%/70% threshold logic with actual `LOADED_PAYLOAD_THRESHOLD = 50%` + transition-counting
- Corrected zone object structure in Step 5 (separate `load_id`/`dump_id` counters; `keys` field on load zones)
- Updated §5.2 zone detection parameters table (replaced stale `load_threshold`/`dump_threshold` with `loaded_payload_threshold = 50`)
- Updated §6.2 zone rule to reflect transition-count classification
- Updated §8.2 programmatic usage to show both import paths (facade and simgen package)
- Updated §3.4 `create_model()` signature to show current arguments (material, density, zone_material_map, machines, etc.)

### Version 1.1 (2026-02-08)
- Added `split_roads_at_intersections()` algorithm (Section 3.2)
- Updated pipeline diagram with Road Splitter component
- Updated component diagram
- Added road splitting business rules
- Updated programmatic usage example

### Version 1.0 (2026-02-05)
- Initial documentation
