import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fielddiff import field_diffs, values_equal  # noqa: E402


def paths(diffs):
    return [d["path"] for d in diffs]


class TestFieldDiffs(unittest.TestCase):
    def test_identical_no_diffs(self):
        self.assertEqual(field_diffs({"a": 1}, {"a": 1}, "$.args"), [])

    def test_changed_leaf(self):
        d = field_diffs({"window": "24h"}, {"window": "7d"}, "$.args")
        self.assertEqual(d, [{"path": "$.args.window", "kind": "changed",
                              "left": "24h", "right": "7d"}])

    def test_added_key(self):
        d = field_diffs({}, {"note": "x"}, "$.result")
        self.assertEqual(d[0]["kind"], "added")
        self.assertIsNone(d[0]["left"])
        self.assertEqual(d[0]["right"], "x")
        self.assertEqual(d[0]["path"], "$.result.note")

    def test_removed_key(self):
        d = field_diffs({"legacy": 1}, {}, "$.args")
        self.assertEqual(d[0]["kind"], "removed")
        self.assertEqual(d[0]["left"], 1)
        self.assertIsNone(d[0]["right"])

    def test_nested_path(self):
        d = field_diffs({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}}, "$.args")
        self.assertEqual(paths(d), ["$.args.a.b.c"])

    def test_list_index_path(self):
        d = field_diffs({"rooms": ["a", "b"]}, {"rooms": ["a", "c"]}, "$.result")
        self.assertEqual(paths(d), ["$.result.rooms[1]"])

    def test_list_added_element(self):
        d = field_diffs([1], [1, 2], "$.args.items")
        self.assertEqual([(x["path"], x["kind"]) for x in d],
                         [("$.args.items[1]", "added")])

    def test_list_removed_element(self):
        d = field_diffs([1, 2], [1], "$.args.items")
        self.assertEqual([(x["path"], x["kind"]) for x in d],
                         [("$.args.items[1]", "removed")])

    def test_dict_key_order_ignored(self):
        self.assertEqual(
            field_diffs({"a": 1, "b": 2}, {"b": 2, "a": 1}, "$"), [])

    def test_output_order_deterministic_regardless_of_key_order(self):
        d1 = field_diffs({"b": 1, "a": 1}, {"b": 2, "a": 2}, "$.x")
        d2 = field_diffs({"a": 1, "b": 1}, {"a": 2, "b": 2}, "$.x")
        self.assertEqual(d1, d2)
        self.assertEqual(paths(d1), ["$.x.a", "$.x.b"])

    def test_type_change_is_changed(self):
        d = field_diffs({"v": "80"}, {"v": 80}, "$.args")
        self.assertEqual(paths(d), ["$.args.v"])
        self.assertEqual(d[0]["kind"], "changed")

    def test_dict_replaced_by_scalar_is_one_changed_entry(self):
        d = field_diffs({"v": {"x": 1}}, {"v": 5}, "$.args")
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["path"], "$.args.v")

    def test_none_vs_value_is_changed(self):
        d = field_diffs({"v": None}, {"v": 0}, "$.args")
        self.assertEqual(len(d), 1)

    def test_multiple_diffs_all_reported(self):
        d = field_diffs({"a": 1, "b": 2, "c": 3}, {"a": 9, "b": 2, "c": 8}, "$")
        self.assertEqual(paths(d), ["$.a", "$.c"])


class TestToleranceAndBoolTraps(unittest.TestCase):
    def test_float_wobble_within_tolerance(self):
        self.assertEqual(field_diffs({"v": 100.0}, {"v": 100.0 * (1 + 5e-7)}, "$"), [])

    def test_float_change_beyond_tolerance(self):
        d = field_diffs({"v": 100.0}, {"v": 100.0 * (1 + 2e-6)}, "$")
        self.assertEqual(paths(d), ["$.v"])

    def test_int_float_same_value_equal(self):
        self.assertTrue(values_equal(22, 22.0))

    def test_bool_never_equals_number(self):
        self.assertFalse(values_equal(True, 1))
        self.assertFalse(values_equal(False, 0))
        self.assertFalse(values_equal(1, True))

    def test_bool_in_args_is_drift_vs_number(self):
        d = field_diffs({"on": True}, {"on": 1}, "$.args")
        self.assertEqual(paths(d), ["$.args.on"])

    def test_bool_vs_bool(self):
        self.assertTrue(values_equal(True, True))
        self.assertFalse(values_equal(True, False))

    def test_bool_nested_in_list(self):
        self.assertFalse(values_equal({"x": [True]}, {"x": [1]}))
        d = field_diffs({"x": [True]}, {"x": [1]}, "$.result")
        self.assertEqual(paths(d), ["$.result.x[0]"])

    def test_string_never_equals_number(self):
        self.assertFalse(values_equal("1", 1))

    def test_zero_tolerance_boundary_with_abs_floor(self):
        # 0.0 vs 5e-10: within the 1e-9 absolute floor -> not drift.
        self.assertEqual(field_diffs({"v": 0.0}, {"v": 5e-10}, "$"), [])
        self.assertEqual(len(field_diffs({"v": 0.0}, {"v": 5e-8}, "$")), 1)


if __name__ == "__main__":
    unittest.main()
