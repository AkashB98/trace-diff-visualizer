"""Aligned, field-level diff between two traces (left vs right).

Pipeline: normalize both traces (volatile fields stripped) -> sequence
alignment (see :mod:`align`) -> per-pair classification and field diffs
(see :mod:`fielddiff`).

Aligned-pair statuses:
  ``matched``      same tool, args and result (within tolerance)
  ``tool_drift``   tool name changed (most severe)
  ``arg_drift``    args changed
  ``result_drift`` result changed (least severe)
  ``missing``      step exists on the left only
  ``extra``        step exists on the right only

When several of tool / args / result differ on one pair, the status is
the most severe (tool > args > result) but *all* field diffs are kept.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from align import align_steps
from fielddiff import DEFAULT_REL_TOL, field_diffs
from trace import Step, Trace

STATUS_MATCHED = "matched"
STATUS_TOOL_DRIFT = "tool_drift"
STATUS_ARG_DRIFT = "arg_drift"
STATUS_RESULT_DRIFT = "result_drift"
STATUS_MISSING = "missing"
STATUS_EXTRA = "extra"

STATUS_ORDER = [STATUS_MATCHED, STATUS_TOOL_DRIFT, STATUS_ARG_DRIFT,
                STATUS_RESULT_DRIFT, STATUS_MISSING, STATUS_EXTRA]

VERDICT_IDENTICAL = "IDENTICAL"
VERDICT_DRIFT = "DRIFT"


def _step_dict(step: Optional[Step]) -> Optional[Dict[str, Any]]:
    if step is None:
        return None
    d = step.to_dict(include_volatile=False)
    d.pop("kind", None)
    return d


@dataclass
class AlignedPair:
    status: str
    left_step: Optional[Dict[str, Any]] = None
    right_step: Optional[Dict[str, Any]] = None
    left_tool: str = ""
    right_tool: str = ""
    arg_diffs: List[Dict[str, Any]] = field(default_factory=list)
    result_diffs: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def field_diffs(self) -> List[Dict[str, Any]]:
        return list(self.arg_diffs) + list(self.result_diffs)

    @property
    def left_seq(self) -> Optional[int]:
        return self.left_step["seq"] if self.left_step else None

    @property
    def right_seq(self) -> Optional[int]:
        return self.right_step["seq"] if self.right_step else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "left_seq": self.left_seq,
            "right_seq": self.right_seq,
            "left_tool": self.left_tool,
            "right_tool": self.right_tool,
            "left_step": copy.deepcopy(self.left_step),
            "right_step": copy.deepcopy(self.right_step),
            "arg_diffs": copy.deepcopy(self.arg_diffs),
            "result_diffs": copy.deepcopy(self.result_diffs),
            "field_diffs": copy.deepcopy(self.field_diffs),
        }


@dataclass
class DiffReport:
    left_meta: Dict[str, Any] = field(default_factory=dict)
    right_meta: Dict[str, Any] = field(default_factory=dict)
    meta_diffs: List[Dict[str, Any]] = field(default_factory=list)
    pairs: List[AlignedPair] = field(default_factory=list)
    left_count: int = 0
    right_count: int = 0

    @property
    def counts(self) -> Dict[str, int]:
        c = {s: 0 for s in STATUS_ORDER}
        for p in self.pairs:
            c[p.status] += 1
        return c

    @property
    def summary_counts(self) -> Dict[str, int]:
        c = self.counts
        c["total"] = len(self.pairs)
        return c

    @property
    def drifted(self) -> bool:
        return bool(self.meta_diffs) or any(
            p.status != STATUS_MATCHED for p in self.pairs)

    @property
    def verdict(self) -> str:
        return VERDICT_DRIFT if self.drifted else VERDICT_IDENTICAL

    def summary(self) -> str:
        lines = [f"verdict={self.verdict} counts={self.summary_counts}"]
        for p in self.pairs:
            if p.status != STATUS_MATCHED:
                lines.append(
                    f"  left_seq={p.left_seq} right_seq={p.right_seq} "
                    f"{p.status}: {p.left_tool!r} -> {p.right_tool!r} "
                    f"fields={[d['path'] for d in p.field_diffs]}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "drifted": self.drifted,
            "left_meta": copy.deepcopy(self.left_meta),
            "right_meta": copy.deepcopy(self.right_meta),
            "meta_diffs": copy.deepcopy(self.meta_diffs),
            "counts": self.summary_counts,
            "left_count": self.left_count,
            "right_count": self.right_count,
            "pairs": [p.to_dict() for p in self.pairs],
        }


def classify(left: Step, right: Step,
             rel_tol: float = DEFAULT_REL_TOL) -> AlignedPair:
    arg_diffs = field_diffs(left.args, right.args, "$.args", rel_tol)
    result_diffs = field_diffs(left.result, right.result, "$.result", rel_tol)
    if left.tool != right.tool:
        status = STATUS_TOOL_DRIFT
    elif arg_diffs:
        status = STATUS_ARG_DRIFT
    elif result_diffs:
        status = STATUS_RESULT_DRIFT
    else:
        status = STATUS_MATCHED
    return AlignedPair(
        status=status,
        left_step=_step_dict(left),
        right_step=_step_dict(right),
        left_tool=left.tool,
        right_tool=right.tool,
        arg_diffs=arg_diffs,
        result_diffs=result_diffs,
    )


def diff_traces(left_trace: Trace, right_trace: Trace,
                rel_tol: float = DEFAULT_REL_TOL) -> DiffReport:
    left = left_trace.normalized()
    right = right_trace.normalized()
    report = DiffReport(
        left_meta=left.meta,
        right_meta=right.meta,
        meta_diffs=field_diffs(left.meta, right.meta, "$.meta", rel_tol),
        left_count=len(left.steps),
        right_count=len(right.steps),
    )
    for li, ri in align_steps(left.steps, right.steps):
        if li is not None and ri is not None:
            report.pairs.append(classify(left.steps[li], right.steps[ri], rel_tol))
        elif li is not None:
            step = left.steps[li]
            report.pairs.append(AlignedPair(
                status=STATUS_MISSING, left_step=_step_dict(step),
                left_tool=step.tool, right_tool=""))
        else:
            assert ri is not None
            step = right.steps[ri]
            report.pairs.append(AlignedPair(
                status=STATUS_EXTRA, right_step=_step_dict(step),
                left_tool="", right_tool=step.tool))
    return report
