"""
Geometry utilities — extracted from simulation_generator.py (behavior-preserving).
"""

import math
from typing import List, Tuple

from backend.scripts.simgen.constants import MAX_REASONABLE_COORD_M

__all__ = [
    "convert_coordinates",
    "calculate_distance",
    "douglas_peucker",
    "perpendicular_distance",
    "point_to_segment_distance",
    "point_to_polyline_distance",
    "project_point_on_polyline",
    "find_contiguous_ranges",
    "compute_road_bounding_box",
    "bboxes_overlap",
    "_remove_consecutive_duplicates",
    "_compute_polyline_length",
    "_compute_overlap_ratio",
    "_warn_coordinate_magnitude",
]


def _warn_coordinate_magnitude(max_abs_coord: float) -> None:
    """
    H1 safety check: emit a loud warning when coordinates are implausibly large
    while in "meters" mode. A magnitude above MAX_REASONABLE_COORD_M almost
    always means millimetre data was mislabelled as meters (a silent 1000x
    mis-scale of the whole map). We warn rather than raise so the live import
    path (which is correctly in meters) is unaffected.
    """
    print(
        "    WARNING: coordinates_in_meters=True but max |coordinate| = "
        f"{max_abs_coord:,.1f} exceeds {MAX_REASONABLE_COORD_M:,.0f} m. "
        "This likely means millimetre data was passed without conversion "
        "(map would be 1000x mis-scaled). Check the caller's unit handling."
    )


def convert_coordinates(
    path_easting: float, path_northing: float, path_elevation: float
) -> Tuple[float, float, float]:
    """Convert database coordinates (mm) to meters."""
    return (
        round(path_easting / 1000.0, 3),
        round(path_northing / 1000.0, 3),
        round(path_elevation / 1000.0, 3),
    )


def calculate_distance(coord1: Tuple, coord2: Tuple) -> float:
    """Calculate 3D distance between two points."""
    dx = coord2[0] - coord1[0]
    dy = coord2[1] - coord1[1]
    dz = coord2[2] - coord1[2] if len(coord1) > 2 and len(coord2) > 2 else 0
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def douglas_peucker(points: List[Tuple], epsilon: float) -> List[Tuple]:
    """Douglas-Peucker path simplification algorithm."""
    if len(points) <= 2:
        return points

    start, end = points[0], points[-1]
    max_dist = 0
    max_idx = 0

    for i in range(1, len(points) - 1):
        dist = perpendicular_distance(points[i], start, end)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > epsilon:
        left = douglas_peucker(points[: max_idx + 1], epsilon)
        right = douglas_peucker(points[max_idx:], epsilon)
        return left[:-1] + right
    else:
        return [start, end]


def perpendicular_distance(point: Tuple, line_start: Tuple, line_end: Tuple) -> float:
    """Calculate perpendicular distance from point to line (2D)."""
    x0, y0 = point[0], point[1]
    x1, y1 = line_start[0], line_start[1]
    x2, y2 = line_end[0], line_end[1]

    line_len = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    if line_len == 0:
        return math.sqrt((x0 - x1) ** 2 + (y0 - y1) ** 2)

    return abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1) / line_len


def point_to_segment_distance(
    point: Tuple[float, float, float],
    seg_start: Tuple[float, float, float],
    seg_end: Tuple[float, float, float],
) -> Tuple[float, float]:
    """
    Calculate minimum 2D distance from point to line segment (clamped projection).

    Unlike perpendicular_distance() which uses infinite line projection,
    this function clamps the projection to the segment endpoints.

    Returns:
        (distance, t) where distance is 2D distance and t is parameter [0,1]
    """
    px, py = point[0], point[1]
    ax, ay = seg_start[0], seg_start[1]
    bx, by = seg_end[0], seg_end[1]

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq == 0:
        dist = math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
        return (dist, 0.0)

    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))

    proj_x = ax + t * dx
    proj_y = ay + t * dy
    dist = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

    return (dist, t)


def point_to_polyline_distance(
    point: Tuple[float, float, float],
    polyline_coords: List[Tuple[float, float, float]],
) -> Tuple[float, float]:
    """
    Calculate min distance from point to polyline and distance-along-polyline
    of the closest projection.

    Returns:
        (min_distance, distance_along_polyline)
    """
    min_dist = float("inf")
    best_along = 0.0
    cumulative_len = 0.0

    for i in range(len(polyline_coords) - 1):
        seg_start = polyline_coords[i]
        seg_end = polyline_coords[i + 1]

        seg_dx = seg_end[0] - seg_start[0]
        seg_dy = seg_end[1] - seg_start[1]
        seg_len = math.sqrt(seg_dx * seg_dx + seg_dy * seg_dy)

        dist, t = point_to_segment_distance(point, seg_start, seg_end)

        if dist < min_dist:
            min_dist = dist
            best_along = cumulative_len + t * seg_len

        cumulative_len += seg_len

    return (min_dist, best_along)


def project_point_on_polyline(
    point: Tuple[float, float, float],
    polyline_coords: List[Tuple[float, float, float]],
) -> float:
    """Project point onto polyline, returning distance-along-polyline."""
    _, distance_along = point_to_polyline_distance(point, polyline_coords)
    return distance_along


def find_contiguous_ranges(indices: List[int]) -> List[Tuple[int, int]]:
    """
    Find contiguous index ranges from a list of indices.

    Example: [0,1,2,5,6,10] -> [(0,2), (5,6), (10,10)]
    """
    if not indices:
        return []

    sorted_idx = sorted(set(indices))
    ranges = []
    range_start = sorted_idx[0]

    for i in range(1, len(sorted_idx)):
        if sorted_idx[i] != sorted_idx[i - 1] + 1:
            ranges.append((range_start, sorted_idx[i - 1]))
            range_start = sorted_idx[i]

    ranges.append((range_start, sorted_idx[-1]))
    return ranges


def compute_road_bounding_box(
    road_coords: List[Tuple[float, float, float]],
    padding: float,
) -> Tuple[float, float, float, float]:
    """Compute axis-aligned bounding box with padding. Returns (min_x, min_y, max_x, max_y)."""
    xs = [c[0] for c in road_coords]
    ys = [c[1] for c in road_coords]
    return (min(xs) - padding, min(ys) - padding, max(xs) + padding, max(ys) + padding)


def bboxes_overlap(
    bbox_a: Tuple[float, float, float, float],
    bbox_b: Tuple[float, float, float, float],
) -> bool:
    """Check if two 2D bounding boxes overlap."""
    return not (
        bbox_a[2] < bbox_b[0]
        or bbox_b[2] < bbox_a[0]
        or bbox_a[3] < bbox_b[1]
        or bbox_b[3] < bbox_a[1]
    )


def _remove_consecutive_duplicates(node_ids: List[int]) -> List[int]:
    """Remove consecutive duplicate node IDs from a list."""
    if not node_ids:
        return node_ids
    result = [node_ids[0]]
    for nid in node_ids[1:]:
        if nid != result[-1]:
            result.append(nid)
    return result


def _compute_polyline_length(coords: List[Tuple[float, float, float]]) -> float:
    """Compute total 2D length of a polyline."""
    length = 0.0
    for i in range(len(coords) - 1):
        dx = coords[i + 1][0] - coords[i][0]
        dy = coords[i + 1][1] - coords[i][1]
        length += math.sqrt(dx * dx + dy * dy)
    return length


def _compute_overlap_ratio(
    line_b_coords: List[Tuple[float, float, float]],
    line_a_coords: List[Tuple[float, float, float]],
    tolerance: float,
    sample_step: float = 2.0,
) -> float:
    """
    Compute what fraction of polyline B's length lies within tolerance of polyline A.

    Walks along B in small steps, checking distance to A at each point.
    Uses Shapely LineString for accurate point-to-polyline distance.

    Args:
        line_b_coords: Polyline B coordinates [(x,y,z), ...]
        line_a_coords: Polyline A coordinates [(x,y,z), ...]
        tolerance: Max distance (m) to be considered "overlapping"
        sample_step: Distance between sample points along B (m)

    Returns:
        Fraction [0.0, 1.0] of B's length within tolerance of A
    """
    from shapely.geometry import LineString

    # Build Shapely geometries (2D only)
    line_a = LineString([(c[0], c[1]) for c in line_a_coords])
    line_b = LineString([(c[0], c[1]) for c in line_b_coords])

    b_length = line_b.length
    if b_length < 1e-6:
        return 0.0

    overlap_length = 0.0
    pos = 0.0
    while pos <= b_length:
        point = line_b.interpolate(pos)
        dist = line_a.distance(point)
        if dist <= tolerance:
            overlap_length += min(sample_step, b_length - pos + sample_step)
        pos += sample_step

    return min(1.0, overlap_length / b_length)
