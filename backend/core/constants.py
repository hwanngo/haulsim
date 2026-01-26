"""
Constants for AMT Cycle Workbench

This module defines enums and constants used throughout the application.
"""

from enum import Enum
from datetime import datetime, timedelta, timezone


class SegmentType(Enum):
    """Segment type enumeration."""

    SPOTTING_AT_SOURCE = "Spotting.At.Source"
    SPOTTING_AT_SINK = "Spotting.At.Sink"
    TRAVELLING_EMPTY = "Travelling.Empty"
    TRAVELLING_FULL = "Travelling.Full"


class ZoneType(Enum):
    """Zone type enumeration."""

    LOAD = "LOAD"
    DUMP = "DUMP"


class SegmentClass(Enum):
    """Segment class enumeration."""

    EMPTY = "EMPTY"
    FULL = "FULL"


# GPS time constants
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)  # GPS time starts Jan 6, 1980
# GPS-UTC offset. 18 leap seconds is correct as of the last leap second
# insertion on 2017-01-01 and remains valid as of 2026. NOTE: this is a static
# value and will silently drift if/when a future leap second is added (the IERS
# announces these in advance) - revisit and update this constant if that happens
# (or source it dynamically).
LEAP_SECONDS = timedelta(seconds=18)

# Aliases for backward compatibility
gps_epoch = GPS_EPOCH
leap_seconds = LEAP_SECONDS
