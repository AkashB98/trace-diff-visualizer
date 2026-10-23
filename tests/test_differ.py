import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from differ import diff_traces  # noqa: E402
from helpers import step, trace_of  # noqa: E402


def statuses(report):
    return [p.status for p in report.pairs]


class TestDiffer(unittest.TestCase):
    def test_identical_traces(self):
        t = trace_of([step(1), step(2, tool="list_rooms")])
        r = diff_traces(t, copy.deepcopy(t))
        self.assertEqual(r.verdict, "IDENTICAL")
        self.assertFalse(r.drifted)
        self.assertEqual(statuses(r), ["matched", "matched"])

    def test_volatile_only_differences_not_drift(self):
        a = trace_of([step(1, timestamp="2026-01-01T00:00:00Z", request_id="a", duration_ms=1.0)])
        b = trace_of([step(1, timestamp="2031-06-06T06:06:06Z", request_id="b", duration_ms=9999.0)],
                     meta={"trace_id": "other", "created_at": "2031-01-01T00:00:00Z"})
        r = diff_traces(a, b)
        self.assertEqual(r.verdict, "IDENTICAL")
        self.assertEqual(r.meta_diffs, [])

    def test_result_drift(self):
        a = trace_of([step(1, result={"target_c": 22.0})])
        b = trace_of([step(1, result={"target_c": 20.5})])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["result_drift"])
        self.assertEqual([d["path"] for d in r.pairs[0].field_diffs], ["$.result.target_c"])

    def test_arg_drift(self):
        a = trace_of([step(1, args={"window": "24h"})])
        b = trace_of([step(1, args={"window": "7d"})])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["arg_drift"])
        self.assertEqual([d["path"] for d in r.pairs[0].arg_diffs], ["$.args.window"])
        self.assertEqual(r.pairs[0].result_diffs, [])

    def test_tool_drift(self):
        a = trace_of([step(1, tool="get_light_state")])
        b = trace_of([step(1, tool="read_light_state")])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["tool_drift"])
        self.assertEqual(r.pairs[0].left_tool, "get_light_state")
        self.assertEqual(r.pairs[0].right_tool, "read_light_state")

    def test_severity_tool_beats_args_and_result_but_all_recorded(self):
        # Same observation (same intent) anchors the pair while tool,
        # args and result all change around it.
        a = trace_of([step(1, tool="alpha", args={"x": 1}, result={"y": 1},
                           observation="do the thing")])
        b = trace_of([step(1, tool="beta", args={"x": 2}, result={"y": 2},
                           observation="do the thing")])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["tool_drift"])
        self.assertEqual([d["path"] for d in r.pairs[0].field_diffs],
                         ["$.args.x", "$.result.y"])

    def test_anchorless_step_is_missing_plus_extra(self):
        # A step whose tool, args AND observation all changed shares no
        # anchor with the original: the aligner honestly reports it as
        # missing + extra rather than inventing a pairing.
        a = trace_of([step(1, tool="alpha", args={"x": 1}, observation="intent one")])
        b = trace_of([step(1, tool="beta", args={"x": 2}, observation="intent two")])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["missing", "extra"])

    def test_severity_args_beats_result(self):
        a = trace_of([step(1, args={"x": 1}, result={"y": 1})])
        b = trace_of([step(1, args={"x": 2}, result={"y": 2})])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["arg_drift"])
        self.assertEqual(len(r.pairs[0].field_diffs), 2)

    def test_missing_step(self):
        a = trace_of([step(1), step(2, tool="check_firmware",
                             args={"device_id": "d"}, observation="verify firmware")])
        b = trace_of([step(1)])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["matched", "missing"])
        self.assertIsNone(r.pairs[1].right_step)
        self.assertEqual(r.pairs[1].left_seq, 2)

    def test_extra_step(self):
        a = trace_of([step(1)])
        b = trace_of([step(1), step(2, tool="run_diagnostics", args={"level": "full"},
                                    observation="run diagnostics")])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["matched", "extra"])
        self.assertIsNone(r.pairs[1].left_step)

    def test_mid_insert_does_not_cascade(self):
        def s(seq, tool, n):
            return step(seq, tool=tool, args={"n": n}, observation=f"do {tool}")
        a = trace_of([s(1, "alpha", 1), s(2, "beta", 2), s(3, "gamma", 3)])
        b = trace_of([s(1, "alpha", 1), s(2, "inserted", 9), s(3, "beta", 2), s(4, "gamma", 3)])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["matched", "extra", "matched", "matched"])
        self.assertEqual(r.counts["extra"], 1)

    def test_counts_include_zeros_and_total(self):
        t = trace_of([step(1)])
        r = diff_traces(t, copy.deepcopy(t))
        self.assertEqual(r.summary_counts,
                         {"matched": 1, "tool_drift": 0, "arg_drift": 0,
                          "result_drift": 0, "missing": 0, "extra": 0, "total": 1})

    def test_meta_nonvolatile_diff_is_drift(self):
        a = trace_of([step(1)])
        b = trace_of([step(1)], meta={"scenario": "different-scenario"})
        r = diff_traces(a, b)
        self.assertTrue(r.drifted)
        self.assertEqual([d["path"] for d in r.meta_diffs], ["$.meta.scenario"])

    def test_report_dict_is_json_shaped_and_deterministic(self):
        import json
        from trace import canonical
        a = trace_of([step(1, result={"v": 1})])
        b = trace_of([step(1, result={"v": 2})])
        d1 = canonical(diff_traces(a, b).to_dict())
        d2 = canonical(diff_traces(copy.deepcopy(a), copy.deepcopy(b)).to_dict())
        self.assertEqual(d1, d2)
        json.loads(d1)  # must be valid JSON

    def test_float_wobble_in_result_not_drift(self):
        a = trace_of([step(1, result={"v": 100.0})])
        b = trace_of([step(1, result={"v": 100.0 * (1 + 5e-7)})])
        self.assertEqual(statuses(diff_traces(a, b)), ["matched"])

    def test_reordering_has_no_move_detection(self):
        # Documented limit: a swapped pair surfaces as missing + matched
        # + extra around the matched anchor, not as a "moved" step.
        def s(seq, tool, n):
            return step(seq, tool=tool, args={"n": n}, observation=f"do {tool}")
        a = trace_of([s(1, "alpha", 1), s(2, "beta", 2)])
        b = trace_of([s(1, "beta", 2), s(2, "alpha", 1)])
        r = diff_traces(a, b)
        self.assertEqual(statuses(r), ["missing", "matched", "extra"])

    def test_empty_traces_identical(self):
        r = diff_traces(trace_of([]), trace_of([]))
        self.assertEqual(r.verdict, "IDENTICAL")
        self.assertEqual(r.pairs, [])


if __name__ == "__main__":
    unittest.main()
