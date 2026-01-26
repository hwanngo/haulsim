"""Tests for audit findings in core reader classes.

Covers:
- H4: LossBucket.__init__ with message=None (no crash, clean fallbacks).
- H5: Cycle.createSegments payload mode computed over the segment slice.
- L5: LossBucket.getHealthInfo (no debug print, consistent with reasonInfo list).
"""

import unittest
from datetime import datetime, timedelta

from core.loss_bucket import lossBucket
from core.cycle import Cycle


class FakeMessage:
    """Minimal message stub exposing the attributes the core classes read."""

    def __init__(self, payload, idx):
        base = datetime(2024, 1, 1) + timedelta(seconds=idx)
        self.payloadPercent = payload
        self.segmentId = 1
        self.actualTime = base
        self.expectedTime = base
        self.cycleDistance = float(idx)
        self.pathEasting = float(idx)
        self.pathNorthing = float(idx)
        self.pathElevation = 0.0
        self.leftEdge = (float(idx), 0.0)
        self.rightEdge = (float(idx), 1.0)
        self.actualSpeed = 5.0
        self.expectedSpeed = 5.0
        self.actualDesiredSpeed = 5.0
        # Keep ASLR constant so all messages fall in a single loss bucket.
        self.actualASLR = 0
        self.expectedASLR = 0
        self.actualASLRName = "Unaccounted"
        self.expectedASLRName = "Unaccounted"
        self.actualASLRCategory = "Unaccounted"
        self.expectedASLRCategory = "Unaccounted"
        # Written back by Segment.createLossBucketsAndTiles.
        self.efficiency = None
        self.painIndex = None
        self.bucketLoss = None


# ---------------------------------------------------------------------------
# H4 - LossBucket.__init__
# ---------------------------------------------------------------------------
class TestLossBucketInitH4(unittest.TestCase):
    def test_message_none_does_not_crash_and_uses_fallbacks(self):
        bucket = lossBucket(5, message=None)
        self.assertEqual(bucket.bucket_id, 5)
        self.assertIsNone(bucket.segmentId)
        self.assertEqual(bucket.actualASLR, "Unaccounted")
        self.assertEqual(bucket.expectedASLR, "Unaccounted")
        self.assertEqual(bucket.actualASLRName, "Unaccounted")
        self.assertEqual(bucket.expectedASLRName, "Unaccounted")
        self.assertEqual(bucket.actualASLRCategory, "Unaccounted")
        self.assertEqual(bucket.expectedASLRCategory, "Unaccounted")

    def test_default_message_arg_does_not_crash(self):
        bucket = lossBucket(0)
        self.assertEqual(bucket.actualASLRName, "Unaccounted")
        self.assertEqual(bucket.expectedASLRName, "Unaccounted")

    def test_real_message_uses_its_values(self):
        msg = FakeMessage(80, 0)
        msg.segmentId = 42
        msg.actualASLR = 7
        msg.expectedASLR = 8
        msg.actualASLRName = "Operating"
        msg.expectedASLRName = "Travelling"
        msg.actualASLRCategory = "Productive"
        msg.expectedASLRCategory = "Planned"

        bucket = lossBucket(3, message=msg)
        self.assertEqual(bucket.segmentId, 42)
        self.assertEqual(bucket.actualASLR, 7)
        self.assertEqual(bucket.expectedASLR, 8)
        self.assertEqual(bucket.actualASLRName, "Operating")
        self.assertEqual(bucket.expectedASLRName, "Travelling")
        self.assertEqual(bucket.actualASLRCategory, "Productive")
        self.assertEqual(bucket.expectedASLRCategory, "Planned")


# ---------------------------------------------------------------------------
# H5 - Cycle.createSegments payload mode over the segment slice
# ---------------------------------------------------------------------------
class TestCreateSegmentsModeH5(unittest.TestCase):
    def test_segment_payload_mode_is_per_segment_not_full_list(self):
        # Designed so the full-list mode differs from the empty-segment mode.
        #
        # payloads = [70, 10, 10, 10, 90, 70, 70, 70, 70, 70]
        # Upward crossing (<=50 -> >50) happens at index 4, so:
        #   empty segment  = [70, 10, 10, 10]   -> per-segment mode = 10
        #   loaded segment = [90, 70, 70, 70, 70, 70]
        # Over the FULL list: count(70) = 6, count(10) = 3 -> full-list mode = 70.
        # A buggy `max(set(payloads[0:cut]), key=payloads.count)` would pick 70
        # for the EMPTY segment (wrong); the fix must yield 10.
        payloads = [70, 10, 10, 10, 90, 70, 70, 70, 70, 70]

        # Sanity: full-list mode (70) differs from the empty-segment mode (10).
        empty_slice = payloads[0:4]
        self.assertEqual(max(set(payloads), key=payloads.count), 70)
        self.assertEqual(max(set(empty_slice), key=empty_slice.count), 10)

        messages = [FakeMessage(p, i) for i, p in enumerate(payloads)]
        indexes = list(range(len(messages)))

        cycle = Cycle(cycle_id=1, machine_id=1, start_time=datetime(2024, 1, 1))
        cycle.createSegments(messages, indexes)

        self.assertEqual(len(cycle.segments), 2)
        empty_segment, loaded_segment = cycle.segments[0], cycle.segments[1]
        self.assertEqual(empty_segment.payload, 10)
        self.assertEqual(loaded_segment.payload, 70)


# ---------------------------------------------------------------------------
# L5 - getHealthInfo no longer prints / no longer indexes a list by str key
# ---------------------------------------------------------------------------
class TestGetHealthInfoL5(unittest.TestCase):
    def test_get_health_info_with_empty_reason_info(self):
        bucket = lossBucket(0, message=None)
        bucket.bucketLoss = 1.0
        bucket.efficiency = 50.0
        result = bucket.getHealthInfo()
        # Must be consistent with reasonInfo being a list (no TypeError).
        self.assertIn("bucketLoss", result)
        self.assertIn("efficiency", result)
        self.assertEqual(result["bucketLoss"], 1.0)
        self.assertEqual(result["efficiency"], 50.0)
        self.assertEqual(result["reasonInfo"], [])


if __name__ == "__main__":
    unittest.main()
