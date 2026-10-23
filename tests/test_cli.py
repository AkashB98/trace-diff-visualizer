import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_DRIFT, EXIT_ERROR, EXIT_IDENTICAL, main as cli_main, make_server  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(ROOT, "fixtures", "baseline.jsonl")
CANDIDATE = os.path.join(ROOT, "fixtures", "candidate.jsonl")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCliCheck(unittest.TestCase):
    def test_check_identical_exit_0(self):
        code, out, _ = run_cli(["check", "--left", BASELINE, "--right", BASELINE])
        self.assertEqual(code, EXIT_IDENTICAL)
        self.assertIn("IDENTICAL", out)

    def test_check_drift_exit_1(self):
        code, out, _ = run_cli(["check", "--left", BASELINE, "--right", CANDIDATE])
        self.assertEqual(code, EXIT_DRIFT)
        self.assertIn("DRIFT", out)

    def test_check_missing_file_exit_2(self):
        code, _, err = run_cli(["check", "--left", BASELINE, "--right", "/tmp/nope-xyz.jsonl"])
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("not found", err)

    def test_check_malformed_file_exit_2(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write("this is not json\n")
        try:
            code, _, _ = run_cli(["check", "--left", path, "--right", BASELINE])
            self.assertEqual(code, EXIT_ERROR)
        finally:
            os.unlink(path)


class TestCliDiff(unittest.TestCase):
    def test_diff_prints_json_report(self):
        code, out, _ = run_cli(["diff", "--left", BASELINE, "--right", CANDIDATE])
        self.assertEqual(code, EXIT_DRIFT)
        report = json.loads(out)
        self.assertEqual(report["verdict"], "DRIFT")
        self.assertEqual(report["counts"]["total"], 8)

    def test_diff_identical_exit_0(self):
        code, out, _ = run_cli(["diff", "--left", BASELINE, "--right", BASELINE])
        self.assertEqual(code, EXIT_IDENTICAL)
        self.assertEqual(json.loads(out)["verdict"], "IDENTICAL")

    def test_diff_missing_file_exit_2(self):
        code, _, _ = run_cli(["diff", "--left", "/tmp/nope-xyz.jsonl", "--right", BASELINE])
        self.assertEqual(code, EXIT_ERROR)


class TestCliRender(unittest.TestCase):
    def test_render_writes_html(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "diff.html")
            code, _, _ = run_cli(["render", "--left", BASELINE, "--right", CANDIDATE,
                                  "--out", out_path])
            self.assertEqual(code, EXIT_IDENTICAL)
            with open(out_path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("DRIFT", content)
            self.assertTrue(content.startswith("<!DOCTYPE html>"))

    def test_render_missing_file_exit_2_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "diff.html")
            code, _, _ = run_cli(["render", "--left", "/tmp/nope-xyz.jsonl",
                                  "--right", BASELINE, "--out", out_path])
            self.assertEqual(code, EXIT_ERROR)
            self.assertFalse(os.path.exists(out_path))


class TestCliServe(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get_content_type(), resp.read()

    def _payload(self):
        with open(BASELINE, encoding="utf-8") as fh:
            left = fh.read()
        with open(CANDIDATE, encoding="utf-8") as fh:
            right = fh.read()
        return {"left": left, "right": right}

    def test_serve_diff(self):
        status, ctype, body = self._post("/diff", self._payload())
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "application/json")
        self.assertEqual(json.loads(body)["verdict"], "DRIFT")

    def test_serve_render(self):
        status, ctype, body = self._post("/render", self._payload())
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "text/html")
        self.assertIn("DRIFT", body.decode())

    def test_serve_accepts_list_of_records(self):
        with open(BASELINE, encoding="utf-8") as fh:
            left = [json.loads(line) for line in fh]
        status, _, body = self._post("/diff", {"left": left, "right": left})
        self.assertEqual(json.loads(body)["verdict"], "IDENTICAL")

    def test_serve_bad_body_400(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/diff", {"left": 42, "right": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_serve_unknown_endpoint_404(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/nope", self._payload())
        self.assertEqual(ctx.exception.code, 404)

    def test_serve_health(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=10) as resp:
            self.assertEqual(json.loads(resp.read())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
