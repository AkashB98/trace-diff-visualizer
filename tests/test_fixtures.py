import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from differ import diff_traces  # noqa: E402
from trace import Trace  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "fixtures", "baseline.jsonl")
CANDIDATE = os.path.join(ROOT, "fixtures", "candidate.jsonl")


class TestFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.left = Trace.load(BASELINE)
        cls.right = Trace.load(CANDIDATE)
        cls.report = diff_traces(cls.left, cls.right)

    def test_fixture_shape(self):
        self.assertEqual(len(self.left), 7)
        self.assertEqual(len(self.right), 7)
        self.assertEqual(self.left.meta["scenario"], "thermostat-not-heating")
        self.assertEqual(self.left.meta["agent"], "helios-home-support-agent")

    def test_pinned_summary_counts(self):
        self.assertEqual(self.report.summary_counts,
                         {"matched": 3, "tool_drift": 1, "arg_drift": 1,
                          "result_drift": 1, "missing": 1, "extra": 1, "total": 8})

    def test_pinned_status_order(self):
        self.assertEqual([p.status for p in self.report.pairs],
                         ["matched", "matched", "arg_drift", "missing", "extra",
                          "result_drift", "tool_drift", "matched"])

    def test_pinned_field_diff_paths(self):
        by_status = {p.status: p for p in self.report.pairs
                     if p.status not in ("matched", "missing", "extra")}
        self.assertEqual([d["path"] for d in by_status["arg_drift"].field_diffs],
                         ["$.args.window"])
        self.assertEqual([d["path"] for d in by_status["result_drift"].field_diffs],
                         ["$.result.target_c"])
        self.assertEqual(by_status["tool_drift"].field_diffs, [])
        self.assertEqual(by_status["tool_drift"].left_tool, "get_light_state")
        self.assertEqual(by_status["tool_drift"].right_tool, "read_light_state")

    def test_extra_is_the_inserted_diagnostics_step(self):
        extra = [p for p in self.report.pairs if p.status == "extra"]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0].right_tool, "run_diagnostics")
        self.assertEqual(extra[0].right_seq, 4)

    def test_missing_is_the_firmware_step(self):
        missing = [p for p in self.report.pairs if p.status == "missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].left_tool, "check_firmware")

    def test_baseline_vs_itself_identical(self):
        r = diff_traces(self.left, Trace.load(BASELINE))
        self.assertEqual(r.verdict, "IDENTICAL")
        self.assertEqual(r.counts["matched"], 7)

    def test_fixtures_contain_no_volatile_leak_in_diff(self):
        # Volatile fields differ wildly between the fixtures, yet exactly
        # 3 steps are matched — proving volatile-only diffs never flag.
        matched_tools = [p.left_tool for p in self.report.pairs if p.status == "matched"]
        self.assertEqual(matched_tools,
                         ["get_device_status", "list_rooms", "create_ticket"])


if __name__ == "__main__":
    unittest.main()
