"""CLI: render | diff | check | demo | serve.

Exit codes:
  check / diff : 0 = identical, 1 = drift, 2 = usage / IO error
  render       : 0 = HTML written, 2 = usage / IO error
  demo / serve : 0 on success, 2 on error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional, Tuple

from differ import diff_traces
from render import render_html
from trace import Trace, canonical

EXIT_IDENTICAL, EXIT_DRIFT, EXIT_ERROR = 0, 1, 2

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load_trace(path: str) -> Optional[Trace]:
    try:
        return Trace.load(path)
    except FileNotFoundError:
        print(f"error: trace file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read trace {path}: {exc}", file=sys.stderr)
    return None


def _load_pair(args) -> Optional[Tuple[Trace, Trace]]:
    left = _load_trace(args.left)
    right = _load_trace(args.right)
    if left is None or right is None:
        return None
    return left, right


def cmd_render(args) -> int:
    pair = _load_pair(args)
    if pair is None:
        return EXIT_ERROR
    html_text = render_html(diff_traces(*pair))
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(html_text)
    except OSError as exc:
        print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"rendered trace diff -> {args.out}")
    return EXIT_IDENTICAL


def cmd_diff(args) -> int:
    pair = _load_pair(args)
    if pair is None:
        return EXIT_ERROR
    report = diff_traces(*pair)
    print(canonical(report.to_dict()))
    return EXIT_DRIFT if report.drifted else EXIT_IDENTICAL


def cmd_check(args) -> int:
    pair = _load_pair(args)
    if pair is None:
        return EXIT_ERROR
    report = diff_traces(*pair)
    print(report.summary())
    return EXIT_DRIFT if report.drifted else EXIT_IDENTICAL


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_DRIFT
    return EXIT_IDENTICAL


# ------------------------------------------------------------------- serve

def _trace_from_payload(value: Any) -> Trace:
    """Accept a trace as JSONL text, a list of line-objects, or a list of
    JSONL strings — whatever the caller has handy."""
    if isinstance(value, str):
        return Trace.from_jsonl(value)
    if isinstance(value, list):
        lines = []
        for item in value:
            lines.append(item if isinstance(item, str) else canonical(item))
        return Trace.from_jsonl("\n".join(lines))
    raise ValueError("trace must be JSONL text or a list of records")


def _report_from_body(body: Dict[str, Any]):
    left = _trace_from_payload(body.get("left", body.get("left_trace")))
    right = _trace_from_payload(body.get("right", body.get("right_trace")))
    return diff_traces(left, right)


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        self._send(code, (canonical(payload) + "\n").encode(), "application/json")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/render", "/diff"):
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            report = _report_from_body(body)
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})
        if self.path == "/render":
            return self._send(200, render_html(report).encode(), "text/html; charset=utf-8")
        return self._send_json(200, report.to_dict())

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  (POST /render, POST /diff, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_IDENTICAL


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trace-diff",
        description="Visual, sequence-aligned diff for agent tool-call traces.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render a self-contained HTML diff")
    r.add_argument("--left", required=True)
    r.add_argument("--right", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_render)

    r = sub.add_parser("diff", help="JSON diff report to stdout")
    r.add_argument("--left", required=True)
    r.add_argument("--right", required=True)
    r.set_defaults(func=cmd_diff)

    r = sub.add_parser("check", help="CI gate: exit 0 identical / 1 drift / 2 error")
    r.add_argument("--left", required=True)
    r.add_argument("--right", required=True)
    r.set_defaults(func=cmd_check)

    r = sub.add_parser("demo", help="run the end-to-end demo")
    r.set_defaults(func=cmd_demo)

    r = sub.add_parser("serve", help="localhost API: POST /render, POST /diff")
    r.add_argument("--port", type=int, default=8765)
    r.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
