import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from align import align_steps, pair_score  # noqa: E402
from helpers import step  # noqa: E402


def seq_steps(tools_args):
    return [step(i + 1, tool=t, args=a, observation=f"obs-{t}-{i}")
            for i, (t, a) in enumerate(tools_args)]


BASE = [("alpha", {"n": 1}), ("beta", {"n": 2}), ("gamma", {"n": 3}),
        ("delta", {"n": 4})]


class TestPairScore(unittest.TestCase):
    def test_identical_signature_scores_highest(self):
        a = step(1, tool="alpha", args={"n": 1}, observation="o")
        self.assertEqual(pair_score(a, step(9, tool="alpha", args={"n": 1}, observation="o")), 5)

    def test_tool_only_match_scores(self):
        a = step(1, tool="alpha", args={"n": 1}, observation="o1")
        b = step(1, tool="alpha", args={"n": 2}, observation="o2")
        self.assertEqual(pair_score(a, b), 2)

    def test_args_only_match_scores(self):
        a = step(1, tool="alpha", args={"n": 1}, observation="o1")
        b = step(1, tool="beta", args={"n": 1}, observation="o2")
        self.assertEqual(pair_score(a, b), 2)

    def test_unrelated_is_negative(self):
        a = step(1, tool="alpha", args={"n": 1}, observation="o1")
        b = step(1, tool="beta", args={"n": 2}, observation="o2")
        self.assertLess(pair_score(a, b), 0)

    def test_result_not_in_signature(self):
        a = step(1, tool="alpha", args={"n": 1}, result={"v": 1}, observation="o")
        b = step(1, tool="alpha", args={"n": 1}, result={"v": 999}, observation="o")
        self.assertEqual(pair_score(a, b), 5)


class TestAlignSteps(unittest.TestCase):
    def test_identical_lists_align_diagonally(self):
        rows = align_steps(seq_steps(BASE), seq_steps(BASE))
        self.assertEqual(rows, [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_mid_insert_is_one_extra_and_downstream_matches(self):
        cand = seq_steps(BASE[:2] + [("inserted", {"n": 99})] + BASE[2:])
        # candidate observations for downstream steps shift index; rebuild
        # them with the tools/args of BASE so only position changed.
        rows = align_steps(seq_steps(BASE), cand)
        extras = [r for r in rows if r[0] is None]
        self.assertEqual(len(extras), 1)
        self.assertEqual(rows[-2:], [(2, 3), (3, 4)])

    def test_mid_insert_with_stable_observations(self):
        left = [step(i + 1, tool=t, args=a, observation=f"do {t}")
                for i, (t, a) in enumerate(BASE)]
        right = [step(1, tool="alpha", args={"n": 1}, observation="do alpha"),
                 step(2, tool="beta", args={"n": 2}, observation="do beta"),
                 step(3, tool="inserted", args={"n": 99}, observation="do inserted"),
                 step(4, tool="gamma", args={"n": 3}, observation="do gamma"),
                 step(5, tool="delta", args={"n": 4}, observation="do delta")]
        rows = align_steps(left, right)
        self.assertEqual(rows, [(0, 0), (1, 1), (None, 2), (2, 3), (3, 4)])

    def test_missing_mid_step(self):
        left = [step(i + 1, tool=t, args=a, observation=f"do {t}")
                for i, (t, a) in enumerate(BASE)]
        right = [step(1, tool="alpha", args={"n": 1}, observation="do alpha"),
                 step(2, tool="gamma", args={"n": 3}, observation="do gamma"),
                 step(3, tool="delta", args={"n": 4}, observation="do delta")]
        rows = align_steps(left, right)
        self.assertEqual(rows, [(0, 0), (1, None), (2, 1), (3, 2)])

    def test_empty_left_all_extra(self):
        rows = align_steps([], seq_steps(BASE[:2]))
        self.assertEqual(rows, [(None, 0), (None, 1)])

    def test_empty_right_all_missing(self):
        rows = align_steps(seq_steps(BASE[:2]), [])
        self.assertEqual(rows, [(0, None), (1, None)])

    def test_both_empty(self):
        self.assertEqual(align_steps([], []), [])

    def test_extra_at_start(self):
        left = [step(1, tool="alpha", args={"n": 1}, observation="do alpha")]
        right = [step(1, tool="new", args={"n": 0}, observation="do new"),
                 step(2, tool="alpha", args={"n": 1}, observation="do alpha")]
        self.assertEqual(align_steps(left, right), [(None, 0), (0, 1)])

    def test_extra_at_end(self):
        left = [step(1, tool="alpha", args={"n": 1}, observation="do alpha")]
        right = [step(1, tool="alpha", args={"n": 1}, observation="do alpha"),
                 step(2, tool="new", args={"n": 0}, observation="do new")]
        self.assertEqual(align_steps(left, right), [(0, 0), (None, 1)])

    def test_arg_drift_still_aligns_as_pair(self):
        left = [step(1, tool="alpha", args={"n": 1}, observation="do alpha")]
        right = [step(1, tool="alpha", args={"n": 2}, observation="do alpha")]
        self.assertEqual(align_steps(left, right), [(0, 0)])

    def test_tool_drift_still_aligns_as_pair(self):
        left = [step(1, tool="alpha", args={"n": 1}, observation="do alpha")]
        right = [step(1, tool="beta", args={"n": 1}, observation="do alpha")]
        self.assertEqual(align_steps(left, right), [(0, 0)])

    def test_duplicate_identical_steps_one_missing(self):
        a = [step(1, tool="poll", args={"id": 1}, observation="poll"),
             step(2, tool="poll", args={"id": 1}, observation="poll")]
        b = [step(1, tool="poll", args={"id": 1}, observation="poll")]
        self.assertEqual(align_steps(a, b), [(0, 0), (1, None)])

    def test_alignment_is_deterministic(self):
        left = seq_steps(BASE)
        right = seq_steps(BASE[:1] + [("x", {"n": 7})] + BASE[1:])
        self.assertEqual(align_steps(left, right), align_steps(left, right))


if __name__ == "__main__":
    unittest.main()
