"""Golden evals for trace-diff-visualizer.

Every eval is deterministic: run_evals.py writes eval_report.json and
the file must be byte-identical across runs (verified via md5). No
timestamps, ports, or temp paths ever enter the report — only names,
booleans, pinned counts and pinned hashes of deterministic output.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_DRIFT, EXIT_ERROR, EXIT_IDENTICAL, main as cli_main, make_server  # noqa: E402
from differ import diff_traces  # noqa: E402
from fielddiff import field_diffs  # noqa: E402
from render import render_html  # noqa: E402
from trace import Trace, canonical  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(ROOT, "fixtures", "baseline.jsonl")
CANDIDATE = os.path.join(ROOT, "fixtures", "candidate.jsonl")
RESULTS = []

EXPECTED_COUNTS = {"matched": 3, "tool_drift": 1, "arg_drift": 1,
                   "result_drift": 1, "missing": 1, "extra": 1, "total": 8}
EXPECTED_STATUSES = ["matched", "matched", "arg_drift", "missing", "extra",
                     "result_drift", "tool_drift", "matched"]


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def main():
    print("== golden evals: trace-diff-visualizer ==")
    left = Trace.load(BASELINE)
    right = Trace.load(CANDIDATE)
    report = diff_traces(left, right)

    # E1: fixture summary counts pinned
    check("E1 fixture summary counts pinned",
          report.summary_counts == EXPECTED_COUNTS, f"{report.summary_counts}")

    # E2: aligned-pair statuses in order pinned
    statuses = [p.status for p in report.pairs]
    check("E2 aligned-pair statuses in order pinned",
          statuses == EXPECTED_STATUSES, f"{statuses}")

    # E3: field-diff paths for the drifted steps pinned
    by_status = {p.status: p for p in report.pairs
                 if p.status in ("arg_drift", "result_drift", "tool_drift")}
    paths_ok = (
        [d["path"] for d in by_status["arg_drift"].field_diffs] == ["$.args.window"]
        and [d["path"] for d in by_status["result_drift"].field_diffs] == ["$.result.target_c"]
        and by_status["tool_drift"].field_diffs == []
        and (by_status["tool_drift"].left_tool, by_status["tool_drift"].right_tool)
        == ("get_light_state", "read_light_state"))
    check("E3 field-diff paths for drifted steps pinned", paths_ok)

    # E4: HTML determinism (two renders byte-identical; hash pinned in report)
    h1 = render_html(report)
    h2 = render_html(diff_traces(Trace.load(BASELINE), Trace.load(CANDIDATE)))
    html_md5 = hashlib.md5(h1.encode()).hexdigest()
    check("E4 HTML determinism", h1 == h2, f"html_md5={html_md5}")

    # E5: identical-pair verdict (baseline vs itself)
    same = diff_traces(left, Trace.load(BASELINE))
    check("E5 identical-pair verdict",
          same.verdict == "IDENTICAL" and same.counts["matched"] == 7,
          f"verdict={same.verdict}")

    # E6: volatile-only differences never drift
    import copy
    skewed = Trace.load(BASELINE)
    for i, s in enumerate(skewed.steps):
        s.timestamp = f"1999-12-31T23:59:{i:02d}Z"
        s.request_id = "volatile-check"
        s.duration_ms = 424242.0
    skewed.meta["trace_id"] = "someone-else"
    skewed.meta["created_at"] = "1999-01-01T00:00:00Z"
    d = diff_traces(left, skewed)
    check("E6 volatile-only differences are not drift", not d.drifted, f"{d.summary_counts}")

    # E7: mid-trace insert = exactly 1 extra, downstream steps matched
    extra = [p for p in report.pairs if p.status == "extra"]
    downstream = report.pairs[-1]
    check("E7 mid-insert is one extra + downstream matched",
          len(extra) == 1 and extra[0].right_tool == "run_diagnostics"
          and downstream.status == "matched",
          f"extra={[p.right_tool for p in extra]}")

    # E8: tolerance + bool traps at the field-diff level
    tol_ok = (field_diffs({"v": 100.0}, {"v": 100.0 * (1 + 5e-7)}, "$") == []
              and len(field_diffs({"v": 100.0}, {"v": 100.0 * (1 + 2e-6)}, "$")) == 1)
    bool_ok = (len(field_diffs({"on": True}, {"on": 1}, "$.args")) == 1
               and field_diffs({"on": True}, {"on": True}, "$.args") == [])
    check("E8 numeric tolerance and bool traps pinned", tol_ok and bool_ok)

    # E9: HTML escaping of hostile trace content
    evil = copy.deepcopy(left)
    evil.steps[0].args = {"device_id": "</script><b>bold</b>"}
    evil_html = render_html(diff_traces(left, evil))
    check("E9 HTML escaping",
          "</script><b>bold</b>" not in evil_html and "<script" not in evil_html
          and "&lt;/script&gt;" in evil_html)

    # E10: CLI check exit codes 0/1/2
    import io
    from contextlib import redirect_stderr, redirect_stdout
    def run(argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cli_main(argv)
    codes = (run(["check", "--left", BASELINE, "--right", BASELINE]),
             run(["check", "--left", BASELINE, "--right", CANDIDATE]),
             run(["check", "--left", BASELINE, "--right", "/tmp/no-such-trace-xyz.jsonl"]))
    check("E10 CLI check exit codes 0/1/2",
          codes == (EXIT_IDENTICAL, EXIT_DRIFT, EXIT_ERROR), f"codes={codes}")

    # E11: serve round-trip (loopback, ephemeral port; port not in report)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with open(BASELINE, encoding="utf-8") as fh:
            left_text = fh.read()
        with open(CANDIDATE, encoding="utf-8") as fh:
            right_text = fh.read()
        payload = json.dumps({"left": left_text, "right": right_text}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/diff", data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        req = urllib.request.Request(f"http://127.0.0.1:{port}/render", data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served_html = resp.read().decode()
        serve_ok = (served["counts"] == EXPECTED_COUNTS and served_html == h1)
    finally:
        server.shutdown()
        server.server_close()
    check("E11 serve round-trip matches local diff + render", serve_ok)

    # E12: JSON report determinism (canonical bytes stable across runs)
    j1 = canonical(diff_traces(Trace.load(BASELINE), Trace.load(CANDIDATE)).to_dict())
    j2 = canonical(diff_traces(Trace.load(BASELINE), Trace.load(CANDIDATE)).to_dict())
    json_md5 = hashlib.md5(j1.encode()).hexdigest()
    check("E12 JSON report determinism", j1 == j2, f"json_md5={json_md5}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    summary = {"passed": passed, "total": total,
               "all_passed": passed == total, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(canonical(summary) + "\n")
    print(f"\n{passed}/{total} evals passed -> evals/eval_report.json")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
