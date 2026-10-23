import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from differ import diff_traces  # noqa: E402
from helpers import step, trace_of  # noqa: E402
from render import render_html  # noqa: E402


def html_for(a, b):
    return render_html(diff_traces(a, b))


class TestRender(unittest.TestCase):
    def test_identical_verdict_badge(self):
        t = trace_of([step(1)])
        out = html_for(t, t)
        self.assertIn("IDENTICAL", out)
        self.assertIn("badge-identical", out)

    def test_drift_verdict_badge(self):
        a = trace_of([step(1, result={"v": 1})])
        b = trace_of([step(1, result={"v": 2})])
        self.assertIn("DRIFT", html_for(a, b))

    def test_self_contained_no_external_assets_no_js(self):
        t = trace_of([step(1)])
        out = html_for(t, t)
        self.assertNotIn("<script", out)
        self.assertNotIn("http://", out.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", out)
        self.assertNotIn("<link", out)
        self.assertIn("<style>", out)

    def test_summary_counts_shown(self):
        a = trace_of([step(1), step(2, tool="x_tool", observation="unique x")])
        b = trace_of([step(1)])
        out = html_for(a, b)
        self.assertIn("matched: 1", out)
        self.assertIn("missing: 1", out)
        self.assertIn("total: 2", out)

    def test_meta_comparison_shown(self):
        t = trace_of([step(1)])
        out = html_for(t, t)
        self.assertIn("helios-home-support-agent", out)
        self.assertIn("Meta identical", out)

    def test_changed_field_highlighted_with_values(self):
        a = trace_of([step(1, args={"window": "24h"})])
        b = trace_of([step(1, args={"window": "7d"})])
        out = html_for(a, b)
        self.assertIn("$.args.window", out)
        self.assertIn("24h", out)
        self.assertIn("7d", out)
        self.assertIn("ARG_DRIFT", out)

    def test_extra_row_is_one_sided(self):
        a = trace_of([step(1)])
        b = trace_of([step(1), step(2, tool="run_diagnostics",
                                    args={"level": "full"}, observation="diag")])
        out = html_for(a, b)
        self.assertIn("run_diagnostics", out)
        self.assertIn("EXTRA", out)
        self.assertIn("card-empty", out)

    def test_missing_row_is_one_sided(self):
        a = trace_of([step(1), step(2, tool="check_firmware", observation="fw check")])
        b = trace_of([step(1)])
        out = html_for(a, b)
        self.assertIn("check_firmware", out)
        self.assertIn("MISSING", out)

    def test_html_escaping_script_payload(self):
        payload = "</script><b>bold</b>"
        a = trace_of([step(1)])
        b = trace_of([step(1, args={"device_id": payload})])
        out = html_for(a, b)
        self.assertNotIn(payload, out)
        self.assertNotIn("<script", out)
        self.assertNotIn("<b>bold</b>", out)
        self.assertIn("&lt;/script&gt;", out)
        self.assertIn("&lt;b&gt;", out)

    def test_html_escaping_in_observation_and_meta(self):
        a = trace_of([step(1, observation="look <img src=x> here")],
                     meta={"scenario": "<evil>"})
        out = html_for(a, a)
        self.assertNotIn("<img src=x>", out)
        self.assertIn("&lt;img src=x&gt;", out)
        self.assertIn("&lt;evil&gt;", out)

    def test_html_escaping_ampersand_and_quotes(self):
        a = trace_of([step(1, args={"note": 'a & "b"'})])
        b = trace_of([step(1, args={"note": 'a & "c"'})])
        out = html_for(a, b)
        self.assertIn("&amp;", out)
        self.assertIn("&quot;", out)

    def test_determinism_byte_identical(self):
        a = trace_of([step(1, result={"v": 1}), step(2, tool="t2", observation="two")])
        b = trace_of([step(1, result={"v": 2}), step(2, tool="t2", observation="two")])
        self.assertEqual(html_for(a, b), html_for(a, b))

    def test_determinism_regardless_of_dict_key_order(self):
        a1 = trace_of([step(1, args={"a": 1, "b": 2})])
        a2 = trace_of([step(1, args={"b": 2, "a": 1})])
        b = trace_of([step(1, args={"a": 1, "b": 3})])
        self.assertEqual(html_for(a1, b), html_for(a2, b))

    def test_no_timestamps_in_output(self):
        a = trace_of([step(1, timestamp="2026-01-15T09:00:00Z")])
        b = trace_of([step(1, timestamp="2031-12-31T23:59:59Z")])
        out = html_for(a, b)
        self.assertNotIn("2026-01-15T09:00:00Z", out)
        self.assertNotIn("2031-12-31", out)
        self.assertNotIn("req-1", out)


if __name__ == "__main__":
    unittest.main()
