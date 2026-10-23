"""End-to-end demo: fixtures -> aligned diff -> HTML -> CI codes -> serve.

Runs fully offline (the serve round-trip is loopback-only, on an
ephemeral port, and shut down before exit). Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_DRIFT, EXIT_ERROR, EXIT_IDENTICAL, main as cli_main, make_server
from differ import diff_traces
from render import render_html
from trace import Trace

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "fixtures", "baseline.jsonl")
CANDIDATE = os.path.join(HERE, "fixtures", "candidate.jsonl")

EXPECTED_COUNTS = {"matched": 3, "tool_drift": 1, "arg_drift": 1,
                   "result_drift": 1, "missing": 1, "extra": 1, "total": 8}
EXPECTED_STATUSES = ["matched", "matched", "arg_drift", "missing", "extra",
                     "result_drift", "tool_drift", "matched"]


def _post(port: int, path: str, payload: dict):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.headers.get_content_type(), resp.read()


def main() -> None:
    print("== 1. load the Helios Home fixtures ==")
    left = Trace.load(BASELINE)
    right = Trace.load(CANDIDATE)
    print(f"   baseline: {len(left)} steps, candidate: {len(right)} steps")
    assert len(left) == 7 and len(right) == 7

    print("\n== 2. sequence-aligned diff (insert must not cascade) ==")
    report = diff_traces(left, right)
    print(f"   verdict={report.verdict} counts={report.summary_counts}")
    for p in report.pairs:
        print(f"   left_seq={p.left_seq} right_seq={p.right_seq} {p.status}")
    assert report.verdict == "DRIFT"
    assert report.summary_counts == EXPECTED_COUNTS, report.summary_counts
    assert [p.status for p in report.pairs] == EXPECTED_STATUSES

    print("\n== 3. identical pair -> IDENTICAL (volatile fields ignored) ==")
    same = diff_traces(left, Trace.load(BASELINE))
    print(f"   verdict={same.verdict} counts={same.summary_counts}")
    assert same.verdict == "IDENTICAL" and not same.drifted

    print("\n== 4. render self-contained HTML (deterministic) ==")
    html1 = render_html(report)
    html2 = render_html(diff_traces(Trace.load(BASELINE), Trace.load(CANDIDATE)))
    assert html1 == html2, "rendering must be byte-identical"
    assert "DRIFT" in html1 and "<script" not in html1
    tmp = tempfile.mkdtemp(prefix="trace-diff-demo-")
    out = os.path.join(tmp, "diff.html")
    code = cli_main(["render", "--left", BASELINE, "--right", CANDIDATE, "--out", out])
    assert code == EXIT_IDENTICAL and os.path.getsize(out) > 0
    print(f"   rendered {len(html1)} bytes -> {out}")

    print("\n== 5. HTML escaping: hostile tool args render as text ==")
    evil = Trace.load(BASELINE)
    evil.steps[0].args = {"device_id": "</script><b>bold</b>"}
    evil_html = render_html(diff_traces(left, evil))
    assert "</script><b>bold</b>" not in evil_html
    assert "&lt;/script&gt;" in evil_html and "&lt;b&gt;" in evil_html
    print("   payload escaped correctly")

    print("\n== 6. CI check exit codes ==")
    c_same = cli_main(["check", "--left", BASELINE, "--right", BASELINE])
    c_drift = cli_main(["check", "--left", BASELINE, "--right", CANDIDATE])
    c_err = cli_main(["check", "--left", BASELINE, "--right", "/tmp/no-such-trace-xyz.jsonl"])
    print(f"   identical={c_same} drift={c_drift} missing-file={c_err}")
    assert (c_same, c_drift, c_err) == (EXIT_IDENTICAL, EXIT_DRIFT, EXIT_ERROR)

    print("\n== 7. live localhost serve round-trip ==")
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with open(BASELINE, encoding="utf-8") as fh:
            left_text = fh.read()
        with open(CANDIDATE, encoding="utf-8") as fh:
            right_text = fh.read()
        payload = {"left": left_text, "right": right_text}
        status, ctype, body = _post(port, "/diff", payload)
        served = json.loads(body)
        assert status == 200 and ctype == "application/json"
        assert served["verdict"] == "DRIFT" and served["counts"] == EXPECTED_COUNTS
        status, ctype, body = _post(port, "/render", payload)
        assert status == 200 and ctype == "text/html"
        assert body.decode() == html1, "served HTML must match local render"
        print(f"   POST /diff -> DRIFT with pinned counts; POST /render -> identical HTML")
    finally:
        server.shutdown()
        server.server_close()

    print("\nDemo OK: aligned diff, HTML, CI gate and serve all verified.")


if __name__ == "__main__":
    main()
