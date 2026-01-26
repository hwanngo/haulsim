"""
obs.py — Structured JSON logging + in-memory metrics for AMT Cycle Workbench.

Usage:
    from backend.obs import log_event, metrics

    log_event("export_start", site="MySite", job="export")
    metrics.incr("export_count")
    metrics.observe("export_duration_last", 1234.5)
    snap = metrics.snapshot()  # -> dict
"""

import sys
import json
import logging
import threading

# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record to stderr."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "event": record.getMessage(),
            # Optional structured fields attached via LogRecord.extra
            "site": getattr(record, "site", None),
            "job": getattr(record, "job", None),
            "stage": getattr(record, "stage", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        # Include any additional extra fields the caller attached
        for key, val in record.__dict__.items():
            if key not in payload and key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "taskName",
            ):
                payload[key] = val
        # Drop None values to keep lines compact
        payload = {k: v for k, v in payload.items() if v is not None}
        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Logger — configure once (idempotent)
# ---------------------------------------------------------------------------


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("amt")
    if logger.handlers:
        return logger  # already configured — skip to avoid duplicates
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_logger = _get_logger()


def log_event(event: str, **fields) -> None:
    """Emit one structured JSON log line to stderr.

    Args:
        event: Human-readable event name (becomes the "event" field).
        **fields: Optional extra key/value pairs (site, job, stage,
                  duration_ms, etc.) merged into the JSON line.
    """
    extra = {k: v for k, v in fields.items()}
    # The LogRecord's msg IS the event string; extra fields travel as record attrs.
    record = logging.LogRecord(
        name="amt",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=event,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    _logger.handle(record)


# ---------------------------------------------------------------------------
# Thread-safe metrics
# ---------------------------------------------------------------------------


class _Metrics:
    """In-memory, thread-safe metrics store.

    Counters (incr) accumulate across the process lifetime.
    Gauges (observe) store the last observed value + an observation count.
    NO cross-restart persistence — intentional.
    """

    # Canonical counter / gauge names that must always appear in snapshot().
    _COUNTER_KEYS = (
        "import_count",
        "export_count",
        "export_failures",
        "records_processed",
    )
    _GAUGE_KEYS = ("export_duration_last",)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {k: 0 for k in self._COUNTER_KEYS}
        self._gauges: dict[str, float] = {}
        self._gauge_counts: dict[str, int] = {}

    def incr(self, name: str, n: int = 1) -> None:
        """Increment counter *name* by *n* (default 1)."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + n

    def observe(self, name: str, value: float) -> None:
        """Record the latest value for gauge *name*."""
        with self._lock:
            self._gauges[name] = value
            self._gauge_counts[name] = self._gauge_counts.get(name, 0) + 1

    def snapshot(self) -> dict:
        """Return a point-in-time copy of all metrics."""
        with self._lock:
            snap: dict = {}
            # Canonical counter keys always present
            for k in self._COUNTER_KEYS:
                snap[k] = self._counters.get(k, 0)
            # Any ad-hoc counters
            for k, v in self._counters.items():
                if k not in snap:
                    snap[k] = v
            # Canonical gauge keys always present (None if never observed)
            for k in self._GAUGE_KEYS:
                snap[k] = self._gauges.get(k, None)
            # Any ad-hoc gauges
            for k, v in self._gauges.items():
                if k not in snap:
                    snap[k] = v
            return snap


# Module-level singleton
metrics = _Metrics()
