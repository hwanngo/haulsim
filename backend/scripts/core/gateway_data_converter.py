"""
Gateway Data Converter

Converts JSON data from gateway parser (GWMReader) to AMTCycleProdInfoMessage objects.

Uses logic from parse_gateway_messages.py to process parser output and convert to database format.

ACTUAL JSON STRUCTURE FROM GWMReader:
{
    "CycleProdInfo": {
        "208188426": [  // IPAddress as key
            [208188426, 1440799449, '2025-09-01T22:03:51.17', 95.185, 95.728, 8026.64, 12320.37, 276.73, 755.52, 12.2, 12, 12, 11.4, 9, 9.3, 0, -34, 7, 27, 5, 0, 58, 31, 0],
            // ... 24 elements per record (first element is IPAddress)
        ]
    }
}

VERIFIED COLUMN MAPPING (based on parse_gateway_messages.py):
JSON Array Index | Database Column | Description | Unit/Notes
-----------------|-----------------|-------------|------------
[0]              | IPAddress | IP Address of machine (208188426) | int
[1]              | segmentId | GPS timestamp (1440799449) | int (seconds since GPS epoch)
[2]              | Time | ISO timestamp string ('2025-09-01T22:03:51.17') | datetime string
[3]              | expectedElapsedTime | Expected elapsed (95.185) | float (already in seconds)
[4]              | actualElapsedTime | Actual elapsed (95.728) | float (already in seconds)
[5]              | pathEasting | X coordinate (8026.64) | float (already in meters)
[6]              | pathNorthing | Y coordinate (12320.37) | float (already in meters)
[7]              | pathElevation | Z coordinate (276.73) | float (already in meters)
[8]              | plannedDistance | Distance (755.52) | float (already in meters)
[9]              | expectedSpeed | Expected speed (12.2) | float (m/s, convert to km/h: *3.6)
[10]             | actualSpeed | Actual speed (12) | float (m/s, convert to km/h: *3.6)
[11]             | expectedDesiredSpeed | Expected desired (12) | float (m/s, convert to km/h: *3.6)
[12]             | actualDesiredSpeed | Actual desired (11.4) | float (m/s, convert to km/h: *3.6)
[13]             | leftWidth | Left width (9) | float (already in meters)
[14]             | rightWidth | Right width (9.3) | float (already in meters)
[15]             | pathBank | Road banking (0) | float (degrees)
[16]             | pathHeading | Direction (-34) | float (degrees)
[17]             | payloadPercent | Payload % (7) | int (0-200, special encoding)
[18]             | expectedSpeedSource | Expected source (27) | int
[19]             | expectedASLR | Expected ASLR (5) | int
[20]             | expectedRegModEnum | Expected reg mod (0) | int
[21]             | actualSpeedSource | Actual source (58) | int
[22]             | actualASLR | Actual ASLR (31) | int
[23]             | actualRegModEnum | Actual reg mod (0) | int

Note: Logic from parse_gateway_messages.py processes 24-element arrays and converts them to dict format
with database column names. Then we convert these dicts to tuple format for AMTCycleProdInfoMessage.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from .reader import AMTCycleProdInfoReader
from .constants import gps_epoch, leap_seconds
from tqdm import tqdm


# Helper functions from parse_gateway_messages.py
def safe_int(val) -> Optional[int]:
    """Safely convert to int."""
    if val is None:
        return None
    try:
        return int(float(val))
    except ValueError, TypeError:
        return None


def safe_payload(val) -> Optional[int]:
    """Handle payload percent special encoding."""
    if val is None:
        return None
    try:
        v = int(val)
        return v if v <= 200 else v - 255
    except ValueError, TypeError:
        return None


def safe_float(val) -> Optional[float]:
    """Safely convert to float (preserves sub-unit precision for coords/speeds)."""
    if val is None:
        return None
    try:
        return float(val)
    except ValueError, TypeError:
        return None


def extract_cp_records(parser_output: Dict[str, Any]) -> Tuple[Dict[str, List], bool]:
    """Extract CycleProdInfo records from parser output."""
    if "CycleProdInfo2" in parser_output and parser_output["CycleProdInfo2"]:
        return parser_output["CycleProdInfo2"], True
    if "CycleProdInfo" in parser_output and parser_output["CycleProdInfo"]:
        return parser_output["CycleProdInfo"], False
    return {}, False


def parse_message_to_dict(data: List) -> Dict[str, Any]:
    """
    Parse a raw message tuple into a dictionary with DB column names.
    Based on parse_gateway_messages.py logic.

    Raw data format (24 fields from parser):
        0:  IPAddress (machine IP address, used to lookup Machine Unique Id)
        1:  segmentId/cycleId
        2:  start_time
        3:  expectedElapsedTime
        4:  actualElapsedTime
        5:  pathEasting
        6:  pathNorthing
        7:  pathElevation
        8:  plannedDistance
        9:  expectedSpeed
        10: actualSpeed
        11: expectedDesiredSpeed
        12: actualDesiredSpeed
        13: leftWidth
        14: rightWidth
        15: pathBank
        16: pathHeading
        17: payloadPercent
        18: expectedSpeedSource
        19: expectedASLR
        20: expectedRegModEnum
        21: actualSpeedSource
        22: actualASLR
        23: actualRegModEnum
    """
    return {
        # Identity carried on the record itself so callers never re-pair by index (H4).
        "IPAddress": safe_int(data[0]),
        "segmentId": safe_int(data[1]),
        # Continuous quantities keep full precision (H1) — only truncating to int
        # silently corrupted coords/speeds/widths/bank on every import.
        "expectedElapsedTime": safe_float(data[3]),
        "actualElapsedTime": safe_float(data[4]),
        "pathEasting": safe_float(data[5]),
        "pathNorthing": safe_float(data[6]),
        "pathElevation": safe_float(data[7]),
        "plannedDistance": safe_float(data[8]),
        "expectedSpeed": safe_float(data[9]),
        "actualSpeed": safe_float(data[10]),
        "expectedDesiredSpeed": safe_float(data[11]),
        "actualDesiredSpeed": safe_float(data[12]),
        "leftWidth": safe_float(data[13]),
        "rightWidth": safe_float(data[14]),
        "pathBank": safe_float(data[15]),
        "pathHeading": safe_float(data[16]),
        "payloadPercent": safe_payload(data[17]),
        # Discrete codes stay integers.
        "expectedSpeedSource": safe_int(data[18]),
        "expectedASLR": safe_int(data[19]),
        "expectedRegModEnum": safe_int(data[20]),
        "actualSpeedSource": safe_int(data[21]),
        "actualASLR": safe_int(data[22]),
        "actualRegModEnum": safe_int(data[23]),
    }


def process_parser_output(parser_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Process parser output and return list of JSON objects with DB column names.
    Based on parse_gateway_messages.py logic - keeps original logic from source file.

    Args:
        parser_output: Raw output from the gateway parser

    Returns:
        List of dictionaries with keys matching database columns (without machineId, segmentId, Time)
    """
    records_by_ip, is_cp2 = extract_cp_records(parser_output)

    if not records_by_ip:
        return []

    all_records = []

    # Count total messages for progress bar
    total_messages = sum(len(messages) for messages in records_by_ip.values())
    print(f"\n[Parser Output] Processing {total_messages:,} messages...")

    with tqdm(total=total_messages, desc="Processing messages", unit="msg") as pbar:
        for ip_address, messages in records_by_ip.items():
            for msg in messages:
                pbar.update(1)
                if len(msg) < 24:
                    continue

                record = parse_message_to_dict(msg)
                all_records.append(record)

    return all_records


def _convert_db_records_to_tuples(
    records: List[Dict[str, Any]], raw_messages: List[List], metadata: Dict[str, Any]
) -> List[tuple]:
    """
    Convert database record dicts (from parse_gateway_messages.py) to tuple format.
    Uses raw_messages to get machineId, segmentId, Time (not present in records).
    """
    tuples = []
    errors = []

    # Ensure records and raw_messages counts match
    if len(records) != len(raw_messages):
        metadata["errors"].append(
            f"Mismatch: {len(records)} records but {len(raw_messages)} raw messages"
        )
        return []

    for idx, (record, raw_msg) in enumerate(zip(records, raw_messages)):
        try:
            tuple_data = _db_record_to_tuple(record, raw_msg)
            if tuple_data:
                tuples.append(tuple_data)
            else:
                errors.append(f"Record {idx}: Failed to convert")
        except Exception as e:
            errors.append(f"Record {idx}: {str(e)}")

    if errors:
        metadata["warnings"].extend(errors[:10])

    return tuples


def _db_record_to_tuple(record: Dict[str, Any], raw_msg: List) -> Optional[tuple]:
    """
    Convert a database record dict (from parse_gateway_messages.py) to tuple format.
    Uses raw_msg to get machineId, segmentId, Time (not present in record dict).

    Returns tuple in format expected by AMTCycleProdInfoMessage (non-27-field format from database):
    [0] machineId
    [1] segmentId
    [2] start_time (datetime or timestamp)
    [3] expectedElapsedTime
    [4] actualElapsedTime
    ...
    [24] cycleDistance (optional, default 0.0)
    """
    try:
        # Get machineId, segmentId, Time from raw message (not present in record dict)
        # Raw message format: [machineId, segmentId, Time, ...]
        machine_id = raw_msg[0] if len(raw_msg) > 0 else 0
        segment_id = raw_msg[1] if len(raw_msg) > 1 else 0
        time_str = raw_msg[2] if len(raw_msg) > 2 else None

        # Parse start_time
        if time_str:
            if isinstance(time_str, str):
                try:
                    start_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    start_time_str = start_time.isoformat()
                except Exception:
                    # Calculate from segmentId if parse fails
                    start_time_gps = segment_id
                    start_time = (
                        gps_epoch + timedelta(seconds=start_time_gps) - leap_seconds
                    )
                    start_time_str = start_time.isoformat()
            else:
                start_time_gps = segment_id
                start_time = (
                    gps_epoch + timedelta(seconds=start_time_gps) - leap_seconds
                )
                start_time_str = start_time.isoformat()
        else:
            # Calculate from segmentId
            start_time_gps = segment_id
            start_time = gps_epoch + timedelta(seconds=start_time_gps) - leap_seconds
            start_time_str = start_time.isoformat()

        # Speed values from GWMReader are in m/s, convert to km/h (* 3.6)
        tuple_data = (
            int(machine_id),  # 0: machineId
            int(segment_id),  # 1: segmentId
            start_time_str,  # 2: start_time (ISO string)
            float(record.get("expectedElapsedTime", 0.0)),  # 3: expectedElapsedTime
            float(record.get("actualElapsedTime", 0.0)),  # 4: actualElapsedTime
            float(record.get("pathEasting", 0.0)),  # 5: pathEasting
            float(record.get("pathNorthing", 0.0)),  # 6: pathNorthing
            float(record.get("pathElevation", 0.0)),  # 7: pathElevation
            float(record.get("plannedDistance", 0.0)),  # 8: plannedDistance
            float(record.get("expectedSpeed", 0.0))
            * 3.6,  # 9: expectedSpeed (m/s -> km/h)
            float(record.get("actualSpeed", 0.0))
            * 3.6,  # 10: actualSpeed (m/s -> km/h)
            float(record.get("expectedDesiredSpeed", 0.0))
            * 3.6,  # 11: expectedDesiredSpeed (m/s -> km/h)
            float(record.get("actualDesiredSpeed", 0.0))
            * 3.6,  # 12: actualDesiredSpeed (m/s -> km/h)
            float(record.get("leftWidth", 0.0)),  # 13: leftWidth
            float(record.get("rightWidth", 0.0)),  # 14: rightWidth
            float(record.get("pathBank", 0.0)),  # 15: pathBank
            float(record.get("pathHeading", 0.0)),  # 16: pathHeading
            int(record.get("payloadPercent", 0)),  # 17: payloadPercent
            int(record.get("expectedSpeedSource", 0)),  # 18: expectedSpeedSource
            int(record.get("expectedASLR", 0)),  # 19: expectedASLR
            int(record.get("expectedRegModEnum", 0)),  # 20: expectedRegModEnum
            int(record.get("actualSpeedSource", 0)),  # 21: actualSpeedSource
            int(record.get("actualASLR", 0)),  # 22: actualASLR
            int(record.get("actualRegModEnum", 0)),  # 23: actualRegModEnum
            float(record.get("cycleDistance", 0.0)),  # 24: cycleDistance
        )

        if len(tuple_data) != 25:
            raise ValueError(f"Invalid tuple length: {len(tuple_data)}, expected 25")

        return tuple_data
    except Exception:
        return None


def extract_zones_from_import(
    parser_output: Dict[str, Any],
) -> Tuple[List, List]:
    """
    Extract Cycles and Zones from imported data using Reader.py standard algorithms.

    Uses parse_cp1_data() per machine to classify segments (Spotting, Travelling)
    and DBSCAN clustering (createLoadDumpAreas) for zone detection.

    Args:
        parser_output: Raw parser output from GWMReader

    Returns:
        Tuple of (all_cycles, all_zones) — Cycle and Zone objects from Reader.py
    """
    records_by_machine, is_cp2 = extract_cp_records(parser_output)

    if not records_by_machine:
        return [], []

    all_cycles = []
    all_zones = []

    for machine_key, raw_messages in records_by_machine.items():
        if not raw_messages:
            continue

        # Build 25-element tuples for this machine
        machine_tuples = []
        for raw_msg in raw_messages:
            if len(raw_msg) < 24:
                continue
            record = parse_message_to_dict(raw_msg)
            t = _db_record_to_tuple(record, raw_msg)
            if t is not None:
                machine_tuples.append(t)

        if not machine_tuples:
            continue

        # Determine machine_id from the first tuple
        machine_id = machine_tuples[0][0]
        machine_info = {
            "Name": f"Machine_{machine_id}",
            "TypeName": "Unknown",
        }

        # Sort tuples by segmentId then actualElapsedTime for correct segment grouping
        machine_tuples.sort(key=lambda x: (x[1], x[4]))

        parse_fn = (
            AMTCycleProdInfoReader.parse_cp2_data
            if is_cp2
            else AMTCycleProdInfoReader.parse_cp1_data
        )
        result = parse_fn(machine_tuples, machine_info)

        if result and result[0]:
            all_cycles.extend(result[0])
        if result and result[1]:
            all_zones.extend(result[1])

    return all_cycles, all_zones


def convert_imported_records_to_telemetry(
    parser_output: Dict[str, Any],
    records: List[Dict[str, Any]],
    sample_interval: int = 5,  # Deprecated: no longer used, kept for backward compatibility
) -> List[Tuple]:
    """
    Convert imported records (dicts) to telemetry tuple format for process_site.

    Args:
        parser_output: Raw parser output containing machineId, segmentId in arrays
        records: List of processed records (dicts) from process_parser_output
        sample_interval: Deprecated - no longer used. Interval is now calculated from
                        actualElapsedTime in the record.

    Returns:
        List of tuples in format:
        (machine_id, segment_id, cycle_id, interval, pathEasting, pathNorthing,
         pathElevation, expectedSpeed, actualSpeed, pathBank, pathHeading,
         leftWidth, rightWidth, payloadPercent)
    """
    # Extract raw messages to get machineId, segmentId
    records_by_ip, _ = extract_cp_records(parser_output)

    # Create mapping from record index to IPAddress (stored as machineId key for backward compat), segmentId
    raw_messages = []
    for ip_address, messages in records_by_ip.items():
        for msg in messages:
            if len(msg) >= 24:
                raw_messages.append(
                    {
                        "machineId": int(msg[0])
                        if msg[0] is not None
                        else 0,  # Actually IPAddress
                        "segmentId": int(msg[1]) if msg[1] is not None else 0,
                    }
                )

    # Ensure records and raw_messages have same length
    if len(records) != len(raw_messages):
        # If mismatch, try to match by creating minimal raw_messages
        if len(raw_messages) < len(records):
            # Extend with default values
            while len(raw_messages) < len(records):
                raw_messages.append({"machineId": 0, "segmentId": 0})
        else:
            # Truncate to match
            raw_messages = raw_messages[: len(records)]

    # Convert to telemetry tuples
    telemetry_tuples = []
    print(f"\n[Converter] Converting {len(records):,} records to telemetry format...")

    for i, record in enumerate(tqdm(records, desc="Converting records", unit="rec")):
        raw_msg = (
            raw_messages[i]
            if i < len(raw_messages)
            else {"machineId": 0, "segmentId": 0}
        )

        # Prefer the identity the record carries about itself (H4); fall back to the
        # positionally-zipped raw message only for older records without it.
        machine_id = record.get("IPAddress")
        if machine_id is None:
            machine_id = raw_msg.get("machineId", 0)  # IPAddress (legacy positional)
        segment_id = record.get("segmentId")
        if segment_id is None:
            segment_id = raw_msg.get("segmentId", 0)

        # Use segmentId as cycle_id (common pattern in telemetry data)
        cycle_id = segment_id

        # Use actualElapsedTime from parser output (in seconds) and convert to milliseconds
        # This ensures correct time calculation in event generation which expects ms
        actual_elapsed_sec = float(record.get("actualElapsedTime", 0.0))
        interval = int(actual_elapsed_sec * 1000)  # Convert seconds to milliseconds

        # Extract fields from record dict
        path_easting = float(record.get("pathEasting", 0.0))
        path_northing = float(record.get("pathNorthing", 0.0))
        path_elevation = float(record.get("pathElevation", 0.0))
        # Speed values from GWMReader are in m/s, convert to km/h
        expected_speed = float(record.get("expectedSpeed", 0.0)) * 3.6
        actual_speed = float(record.get("actualSpeed", 0.0)) * 3.6
        path_bank = float(record.get("pathBank", 0.0))
        path_heading = float(record.get("pathHeading", 0.0))
        left_width = float(record.get("leftWidth", 0.0))
        right_width = float(record.get("rightWidth", 0.0))
        payload_percent = int(record.get("payloadPercent", 0))

        # Handle payload > 200
        if payload_percent > 200:
            payload_percent = payload_percent - 255

        # Create tuple in format expected by process_site
        telemetry_tuple = (
            machine_id,  # 0: IPAddress (used to lookup machine info)
            segment_id,  # 1: segment_id
            cycle_id,  # 2: cycle_id
            interval,  # 3: interval
            path_easting,  # 4: pathEasting
            path_northing,  # 5: pathNorthing
            path_elevation,  # 6: pathElevation
            expected_speed,  # 7: expectedSpeed
            actual_speed,  # 8: actualSpeed
            path_bank,  # 9: pathBank
            path_heading,  # 10: pathHeading
            left_width,  # 11: leftWidth
            right_width,  # 12: rightWidth
            payload_percent,  # 13: payloadPercent
        )

        telemetry_tuples.append(telemetry_tuple)

    # Sort by machine_id, cycle_id, segment_id, interval
    telemetry_tuples.sort(key=lambda x: (x[0], x[2], x[1], x[3]))

    return telemetry_tuples
