"""Field-level recursive diffs for args / result payloads.

``field_diffs(left, right, path)`` walks two JSON-like values and returns
one entry per leaf difference::

    {"path": "$.args.window", "kind": "changed", "left": "24h", "right": "7d"}
    {"path": "$.result.note", "kind": "added",   "left": None,  "right": "x"}
    {"path": "$.args.legacy", "kind": "removed", "left": 1,     "right": None}

Comparison rules:
  * dict key order is ignored (keys are visited in sorted order, so the
    output order is deterministic regardless of input ordering);
  * numbers compare with relative tolerance ``1e-6`` (plus a tiny absolute
    floor) — float wobble is not drift;
  * a bool is never equal to a number (Python's ``True == 1`` trap):
    bool-vs-anything compares by exact type and value;
  * lists are order-sensitive and compared index by index; surplus
    elements are reported as added / removed at their index path.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List

DEFAULT_REL_TOL = 1e-6
DEFAULT_ABS_TOL = 1e-9


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def values_equal(a: Any, b: Any, rel_tol: float = DEFAULT_REL_TOL,
                 abs_tol: float = DEFAULT_ABS_TOL) -> bool:
    """Tolerant deep equality consistent with :func:`field_diffs`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if _is_num(a) and _is_num(b):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(values_equal(a[k], b[k], rel_tol, abs_tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            values_equal(x, y, rel_tol, abs_tol) for x, y in zip(a, b))
    if type(a) is not type(b) and not (_is_num(a) and _is_num(b)):
        # e.g. "1" vs 1, None vs 0 — different JSON types are not equal,
        # except int/float which are both JSON numbers (handled above).
        if a is None or b is None:
            return a is b
        if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
            return False
        if isinstance(a, str) or isinstance(b, str):
            return False
    return a == b


def _entry(path: str, kind: str, left: Any, right: Any) -> Dict[str, Any]:
    return {"path": path, "kind": kind,
            "left": copy.deepcopy(left), "right": copy.deepcopy(right)}


def field_diffs(left: Any, right: Any, path: str = "$",
                rel_tol: float = DEFAULT_REL_TOL) -> List[Dict[str, Any]]:
    """Recursive walk producing one entry per differing leaf."""
    out: List[Dict[str, Any]] = []
    _walk(left, right, path, rel_tol, out)
    return out


def _walk(left: Any, right: Any, path: str, rel_tol: float,
          out: List[Dict[str, Any]]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            sub = f"{path}.{key}"
            if key not in right:
                out.append(_entry(sub, "removed", left[key], None))
            elif key not in left:
                out.append(_entry(sub, "added", None, right[key]))
            else:
                _walk(left[key], right[key], sub, rel_tol, out)
        return
    if isinstance(left, list) and isinstance(right, list):
        for i in range(max(len(left), len(right))):
            sub = f"{path}[{i}]"
            if i >= len(right):
                out.append(_entry(sub, "removed", left[i], None))
            elif i >= len(left):
                out.append(_entry(sub, "added", None, right[i]))
            else:
                _walk(left[i], right[i], sub, rel_tol, out)
        return
    if not values_equal(left, right, rel_tol=rel_tol):
        out.append(_entry(path, "changed", left, right))
