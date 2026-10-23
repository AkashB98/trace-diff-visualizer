"""Shared builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trace import Step, Trace  # noqa: E402


def step(seq, tool="get_device_status", args=None, result=None,
         observation=None, **volatile):
    return Step(
        seq=seq,
        observation=observation if observation is not None else f"obs {seq} {tool}",
        tool=tool,
        args=args if args is not None else {"device_id": "thermostat_hallway"},
        result=result if result is not None else {"ok": True},
        timestamp=volatile.get("timestamp", "2026-01-15T09:00:00Z"),
        request_id=volatile.get("request_id", f"req-{seq}"),
        duration_ms=volatile.get("duration_ms", 1.0),
    )


def trace_of(steps, meta=None):
    base = {"agent": "helios-home-support-agent", "scenario": "thermostat-not-heating",
            "format": "tool-call-trace/1", "trace_id": "t-1",
            "created_at": "2026-01-15T09:00:00Z"}
    if meta:
        base.update(meta)
    return Trace(meta=base, steps=list(steps))
