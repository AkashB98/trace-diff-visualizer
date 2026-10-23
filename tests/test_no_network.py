"""No-network enforcement: with sockets blocked, loading, aligning,
diffing and rendering must all still work. (``serve`` is the only
intentional exception — it binds loopback on demand, and is not used
here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "fixtures", "baseline.jsonl")
CANDIDATE = os.path.join(ROOT, "fixtures", "candidate.jsonl")


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from differ import diff_traces
        from render import render_html
        from trace import Trace
        left = Trace.load(BASELINE)
        right = Trace.load(CANDIDATE)
        report = diff_traces(left, right)
        self.assertEqual(report.verdict, "DRIFT")
        self.assertIn("DRIFT", render_html(report))

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("trace", "fielddiff", "align", "differ", "render", "cli", "demo"):
            sys.modules.pop(mod, None)
        import align, cli, demo, differ, fielddiff, render, trace  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
