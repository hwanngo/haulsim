"""
Tests for import-path audit fixes:

  H1 - imported telemetry must preserve float precision (not truncate to int)
  H4 - each parsed record must carry its own IP + segmentId (no index re-pairing)
  H3 - GWMReader clone must accept file paths containing spaces (one --files= each)
  M2 - GWMReader clone must exit non-zero when every input file fails to parse
"""

import os
import subprocess
import sys
import unittest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BACKEND_DIR)

from core.gateway_data_converter import (  # noqa: E402
    parse_message_to_dict,
    process_parser_output,
    convert_imported_records_to_telemetry,
)

GWM_EXE = os.path.normpath(
    os.path.join(BACKEND_DIR, "..", "executables", "GWMReader.exe")
)


def make_msg(ip, seg, easting=8026.64, speed=12.2, payload=75):
    # 24-field message matching parse_message_to_dict indices.
    return [
        ip,
        seg,
        "",
        95.18,
        95.72,
        easting,
        12320.37,
        276.73,
        755.52,
        speed,
        12.0,
        12.0,
        11.4,
        9.0,
        9.3,
        1.5,
        45.0,
        payload,
        5,
        5,
        0,
        58,
        31,
        0,
    ]


class TestPrecision(unittest.TestCase):
    def test_float_fields_keep_precision(self):
        """H1: coords/speeds/widths/bank must not be truncated to int."""
        d = parse_message_to_dict(make_msg(170393867, 1440799001))
        self.assertEqual(d["pathEasting"], 8026.64)
        self.assertEqual(d["pathNorthing"], 12320.37)
        self.assertEqual(d["expectedSpeed"], 12.2)
        self.assertEqual(d["leftWidth"], 9.0)
        self.assertEqual(d["pathBank"], 1.5)

    def test_integer_fields_stay_int(self):
        """H1: genuinely-integer fields remain ints."""
        d = parse_message_to_dict(make_msg(170393867, 1440799001))
        self.assertEqual(d["payloadPercent"], 75)
        self.assertIsInstance(d["payloadPercent"], int)
        self.assertEqual(d["expectedASLR"], 5)
        self.assertIsInstance(d["expectedASLR"], int)


class TestRecordCarriesIdentity(unittest.TestCase):
    def test_record_carries_ip_and_segment(self):
        """H4: each record self-describes its IP + segmentId (no positional re-pair)."""
        parser_output = {
            "CycleProdInfo": {
                "111": [make_msg(111, 1001)],
                "222": [make_msg(222, 2002)],
            }
        }
        records = process_parser_output(parser_output)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["IPAddress"], 111)
        self.assertEqual(records[0]["segmentId"], 1001)
        self.assertEqual(records[1]["IPAddress"], 222)
        self.assertEqual(records[1]["segmentId"], 2002)

    def test_convert_maps_ip_from_record(self):
        """H4: telemetry tuples carry the correct IP / segment from the record."""
        parser_output = {
            "CycleProdInfo": {
                "111": [make_msg(111, 1001)],
                "222": [make_msg(222, 2002)],
            }
        }
        records = process_parser_output(parser_output)
        tuples = convert_imported_records_to_telemetry(parser_output, records)
        ips = sorted(t[0] for t in tuples)
        self.assertEqual(ips, [111, 222])
        by_ip = {t[0]: t for t in tuples}
        self.assertEqual(by_ip[111][1], 1001)  # segment_id
        self.assertEqual(by_ip[222][1], 2002)


class TestGwmClone(unittest.TestCase):
    def _run(self, args):
        return subprocess.run(
            [sys.executable, GWM_EXE] + args, capture_output=True, text=True
        )

    def test_path_with_spaces(self):
        """H3: a .gwm path containing spaces must be read (passed as one --files=)."""
        import tempfile

        with tempfile.TemporaryDirectory() as base:
            spaced = os.path.join(base, "dir with spaces")
            os.makedirs(spaced)
            gwm = os.path.join(spaced, "cap.gwm")
            with open(gwm, "w") as f:
                f.write("# header\n")
                f.write("|".join(str(x) for x in make_msg(170393867, 1001)) + "\n")
            res = self._run(["--sitename=ESC", f"--files={gwm}"])
            self.assertEqual(res.returncode, 0, res.stdout)
            import json

            doc = json.loads(res.stderr)
            self.assertIn("170393867", doc["CycleProdInfo"])
            self.assertEqual(len(doc["CycleProdInfo"]["170393867"]), 1)

    def test_all_files_fail_is_nonzero(self):
        """M2: if no records are parsed at all, exit non-zero (don't fake success)."""
        res = self._run(["--sitename=ESC", "--files=/no/such/file.gwm"])
        self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
