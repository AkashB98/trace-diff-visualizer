import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import step, trace_of  # noqa: E402
from trace import Trace  # noqa: E402


class TestTraceLoading(unittest.TestCase):
    def test_round_trip_jsonl(self):
        t = trace_of([step(1), step(2, tool="list_rooms")])
        t2 = Trace.from_jsonl(t.to_jsonl())
        self.assertEqual(len(t2), 2)
        self.assertEqual(t2.steps[1].tool, "list_rooms")

    def test_meta_parsed_without_kind(self):
        t = Trace.from_jsonl(trace_of([step(1)]).to_jsonl())
        self.assertEqual(t.meta["agent"], "helios-home-support-agent")
        self.assertNotIn("kind", t.meta)

    def test_steps_sorted_by_seq(self):
        text = ('{"kind":"meta","agent":"a"}\n'
                '{"kind":"step","seq":2,"observation":"b","tool":"t2","args":{},"result":{}}\n'
                '{"kind":"step","seq":1,"observation":"a","tool":"t1","args":{},"result":{}}\n')
        t = Trace.from_jsonl(text)
        self.assertEqual([s.seq for s in t.steps], [1, 2])

    def test_invalid_json_raises_with_line_number(self):
        with self.assertRaises(ValueError) as ctx:
            Trace.from_jsonl('{"kind":"meta"}\nnot json\n')
        self.assertIn("line 2", str(ctx.exception))

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            Trace.from_jsonl('{"kind":"mystery"}\n')

    def test_blank_lines_ignored(self):
        t = Trace.from_jsonl('\n{"kind":"meta","agent":"a"}\n\n')
        self.assertEqual(t.meta["agent"], "a")

    def test_save_and_load_file(self):
        t = trace_of([step(1)])
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            t.save(path)
            self.assertEqual(Trace.load(path).steps[0].tool, t.steps[0].tool)
        finally:
            os.unlink(path)

    def test_normalized_strips_step_volatile(self):
        s = step(1, timestamp="2030-01-01T00:00:00Z", request_id="zzz", duration_ms=999.0)
        n = trace_of([s]).normalized()
        self.assertIsNone(n.steps[0].timestamp)
        self.assertIsNone(n.steps[0].request_id)
        self.assertIsNone(n.steps[0].duration_ms)

    def test_normalized_strips_meta_volatile_only(self):
        n = trace_of([step(1)]).normalized()
        self.assertNotIn("trace_id", n.meta)
        self.assertNotIn("created_at", n.meta)
        self.assertEqual(n.meta["scenario"], "thermostat-not-heating")

    def test_normalized_does_not_mutate_original(self):
        t = trace_of([step(1)])
        t.normalized()
        self.assertEqual(t.steps[0].request_id, "req-1")
        self.assertIn("trace_id", t.meta)

    def test_normalized_args_are_deep_copies(self):
        t = trace_of([step(1, args={"nested": {"x": 1}})])
        n = t.normalized()
        n.steps[0].args["nested"]["x"] = 99
        self.assertEqual(t.steps[0].args["nested"]["x"], 1)


if __name__ == "__main__":
    unittest.main()
