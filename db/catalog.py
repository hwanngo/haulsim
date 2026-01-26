"""
Shared site / machine catalog + haul-cycle geometry.

Single source of truth used by BOTH:
  - db/generate_seed.py        -> DB seed (coords in millimetres)
  - tools/generate_gwm.py      -> .gwm import sample (coords in metres)

Keeping geometry here guarantees the Dockerized-DB data and the uploadable
import sample describe the same mine, so either ingestion path yields the same
kind of model/events.

Deterministic: callers seed `random` before iterating.
"""
import math


def ip2int(dotted: str) -> int:
    a, b, c, d = (int(x) for x in dotted.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


# Fleet is CATERPILLAR-only. `type` is the machine TypeName as it would appear in
# the production DB (e.g. "Cat 793F CMD"); the model generator's
# extract_machine_model() pulls the model token ("793F") from it and enriches the
# hauler with real specs from reference_data/machines.json. Write AC-drive models
# WITHOUT a space ("794AC", not "794 AC") so the token includes the suffix.
#
# (SiteId, "Site Name", "Short", [ (name, type, autonomous, ip_int), ... ], cycles_per_machine)
SITES = [
    # BHP Escondida (copper, Chile) — core CAT mining fleet.
    (1, "BhpEscondida", "ESC", [
        ("ESC_793F_01",  "Cat 793F CMD",  0, ip2int("10.40.1.11")),
        ("ESC_793F_02",  "Cat 793F CMD",  0, ip2int("10.40.1.12")),
        ("ESC_794AC_01", "Cat 794AC CMD", 1, ip2int("10.40.1.13")),  # autonomous (Command)
        ("ESC_794AC_02", "Cat 794AC CMD", 1, ip2int("10.40.1.14")),  # autonomous (Command)
        ("ESC_789_01",   "Cat 789 CMD",   0, ip2int("10.40.1.15")),
        ("ESC_785_01",   "Cat 785 CMD",   0, ip2int("10.40.1.16")),
    ], 3),
    # BHP Spence (copper, Chile) — ultra-class haulers.
    (2, "BhpSpence", "SPE", [
        ("SPE_797F_01",  "Cat 797F CMD",  0, ip2int("10.50.1.21")),
        ("SPE_797F_02",  "Cat 797F CMD",  0, ip2int("10.50.1.22")),
        ("SPE_793F_01",  "Cat 793F CMD",  0, ip2int("10.50.1.23")),
        ("SPE_777G_01",  "Cat 777G CMD",  0, ip2int("10.50.1.24")),
        ("SPE_798AC_01", "Cat 798AC CMD", 1, ip2int("10.50.1.25")),  # autonomous (Command)
    ], 3),
    # Caterpillar Tinaja Hills Demonstration & Learning Center (Arizona, USA) —
    # showcases the full CAT off-highway/mining truck range.
    (3, "CatTinajaHills", "TJH", [
        ("TJH_798AC_01", "Cat 798AC CMD", 1, ip2int("10.60.1.31")),  # autonomous (Command)
        ("TJH_796AC_01", "Cat 796AC CMD", 1, ip2int("10.60.1.32")),  # autonomous (Command)
        ("TJH_777G_01",  "Cat 777G CMD",  0, ip2int("10.60.1.33")),
        ("TJH_775G_01",  "Cat 775G CMD",  0, ip2int("10.60.1.34")),
        ("TJH_773G_01",  "Cat 773G CMD",  0, ip2int("10.60.1.35")),
        ("TJH_772G_01",  "Cat 772G CMD",  0, ip2int("10.60.1.36")),
        ("TJH_770G_01",  "Cat 770G CMD",  0, ip2int("10.60.1.37")),
    ], 3),
]

# Per-site zone geometry: load/dump centres (local metres) and elevations. Absolute
# elevations approximate the real sites; load > dump so loaded trucks roll downhill
# to the dump, with the haul grade kept inside the 7-10% sustained design max (see
# reference_data/haul_road_design.json). Approx real coordinates/elevations in comments.
SITE_GEO = {
    # Escondida ~ -24.27, -69.07, ~3100 m elev, ~645 m-deep pit (copper). Haul ~1.87 km @ ~6.9%.
    1: dict(load=(8000.0, 12000.0),  dump=(9550.0, 13050.0),  z_load=3140.0, z_dump=3010.0),
    # Spence ~ -22.74, -69.27, ~1700 m elev, ~850 m-deep pit (copper). Haul ~1.78 km @ ~6.7%.
    2: dict(load=(15200.0, 21000.0), dump=(13800.0, 22100.0), z_load=1730.0, z_dump=1610.0),
    # Cat Tinaja Hills ~ 31.82, -111.13, ~1359 m elev, demonstration center. Haul ~2.66 km @ ~3.0%.
    3: dict(load=(3200.0, 4100.0),   dump=(5400.0, 5600.0),   z_load=1380.0, z_dump=1300.0),
}

# Primary material hauled per site (keys -> reference_data/materials.json). Tinaja
# Hills is a demonstration site, not a producing mine, so it uses generic waste rock.
SITE_MATERIAL = {1: "copper_ore", 2: "copper_ore", 3: "overburden"}

ROAD_STEP = 5.0     # metres between haul samples -> dense enough for road detection
STOP_POINTS = 26    # samples parked in a zone -> exceeds min_stop_count(20)
LANE_W = 9.0        # half road width (m) each side
SAMPLE_SEC = 5.0    # actualElapsedTime per sample (seconds)


def heading_deg(dx, dy):
    """Compass-ish bearing in [-180,180] from a 2-D delta."""
    return round(math.degrees(math.atan2(dx, dy)), 2)


def _pt(e, n, z, es, asp, bank, hdg, pl):
    return dict(e=e, n=n, z=z, es=es, asp=asp, bank=bank, hdg=hdg, pl=pl, sec=SAMPLE_SEC)


def zone_points(cx, cy, z, loaded_when_parked, rng):
    """Parked-in-zone samples: near-zero speed, jittered around the centre.
    LOAD zone: empty most of the time, fills at the end -> avg payload <30 (LOAD)
    DUMP zone: full most of the time, empties at the end -> avg payload >70 (DUMP)."""
    pts = []
    ramp = [80, 60, 40, 20, 0] if loaded_when_parked else [20, 40, 60, 80, 100]
    base = 100 if loaded_when_parked else 0
    for i in range(STOP_POINTS):
        pl = base if i < STOP_POINTS - len(ramp) else ramp[i - (STOP_POINTS - len(ramp))]
        pts.append(_pt(
            cx + rng.uniform(-6, 6), cy + rng.uniform(-6, 6), z + rng.uniform(-0.3, 0.3),
            rng.uniform(0.0, 0.4), rng.uniform(0.0, 0.4),
            rng.uniform(-1, 1), heading_deg(rng.uniform(-1, 1), 1), pl,
        ))
    return pts


def road_points(a, b, za, zb, payload, rng):
    """Evenly spaced moving samples from a->b with slight lateral wander."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    n = max(2, int(dist // ROAD_STEP))
    px, py = -dy / dist, dx / dist           # unit perpendicular (lane wander)
    hdg = heading_deg(dx, dy)
    pts = []
    for i in range(n + 1):
        t = i / n
        wander = rng.uniform(-1.5, 1.5)
        spd = rng.uniform(9.5, 12.5)
        pts.append(_pt(
            ax + dx * t + px * wander, ay + dy * t + py * wander,
            za + (zb - za) * t + rng.uniform(-0.2, 0.2),
            spd + rng.uniform(-0.5, 0.5), spd,
            rng.uniform(-2, 4), hdg, payload,
        ))
    return pts


def cycle_legs(geo, rng):
    """One haul cycle as 4 ordered legs (each a list of point dicts), in metres:
    load (empty->full) -> haul loaded -> dump (full->empty) -> return empty."""
    load, dump = geo["load"], geo["dump"]
    zl, zd = geo["z_load"], geo["z_dump"]
    return [
        zone_points(*load, zl, loaded_when_parked=False, rng=rng),
        road_points(load, dump, zl, zd, payload=100, rng=rng),
        zone_points(*dump, zd, loaded_when_parked=True, rng=rng),
        road_points(dump, load, zd, zl, payload=0, rng=rng),
    ]
