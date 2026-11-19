"""Tests for the interactive review core logic (ReviewEdit)."""

import unittest

from uefi_policy.policy import ReviewOption, save_review
from uefi_policy.review import ACCEPT, REJECT, UNKNOWN, ReviewEdit


def mk(path="hp-x/Foo", current="On", accepted=("On",), rejected=(), unknown=("Off", "Auto")):
    opt = ReviewOption(path=path, current=current,
                       accept=list(accepted), reject=list(rejected),
                       unknown=list(unknown))
    return ReviewEdit.from_review(opt)


class ReviewEditValuesTest(unittest.TestCase):
    def test_values_sorted_union(self):
        e = mk()
        self.assertEqual(e.values(), ["Auto", "Off", "On"])

    def test_current_included_even_if_in_no_set(self):
        opt = ReviewOption(path="hp-x/F", current="X", accept=[], reject=[], unknown=[])
        e = ReviewEdit.from_review(opt)
        self.assertEqual(e.values(), ["X"])

    def test_classify(self):
        e = mk()
        self.assertEqual(e.classify("On"), ACCEPT)
        self.assertEqual(e.classify("Off"), UNKNOWN)


class ReviewEditCursorTest(unittest.TestCase):
    def test_initial_cursor_highlights_current(self):
        e = mk()  # current "On", values [Auto, Off, On]
        self.assertEqual(e.values()[e.cursor], "On")

    def test_initial_cursor_highlights_current_even_if_in_no_set(self):
        opt = ReviewOption(path="hp-x/F", current="Z", accept=["A"], reject=["B"], unknown=[])
        e = ReviewEdit.from_review(opt)
        self.assertEqual(e.values(), ["A", "B", "Z"])
        self.assertEqual(e.cursor, 2)  # "Z" is highlighted

    def test_initial_cursor_zero_when_no_current(self):
        opt = ReviewOption(path="hp-x/F", current=None, accept=["B"], reject=["A"], unknown=[])
        e = ReviewEdit.from_review(opt)
        self.assertEqual(e.cursor, 0)

    def test_move_up_down_clamped(self):
        e = mk()
        e.move_up()
        self.assertEqual(e.values()[e.cursor], "Off")
        e.move_up()
        self.assertEqual(e.values()[e.cursor], "Auto")
        e.move_up()  # already at top
        self.assertEqual(e.values()[e.cursor], "Auto")
        e.move_down()
        e.move_down()
        e.move_down()  # overflow
        self.assertEqual(e.values()[e.cursor], "On")


class ReviewEditOpsTest(unittest.TestCase):
    def test_accept(self):
        e = mk()
        e.cursor = e.values().index("Auto")  # highlight "Auto"
        e.assign(ACCEPT)
        self.assertEqual(e.classify("Auto"), ACCEPT)
        self.assertEqual(e.classify("On"), ACCEPT)

    def test_reject(self):
        e = mk()
        e.cursor = e.values().index("On")
        e.assign(REJECT)
        self.assertEqual(e.classify("On"), REJECT)

    def test_undecided(self):
        e = mk()
        e.cursor = e.values().index("On")
        e.assign(UNKNOWN)
        self.assertEqual(e.classify("On"), UNKNOWN)

    def test_moves_value_to_single_set(self):
        e = mk()
        e.cursor = e.values().index("On")
        e.assign(REJECT)
        self.assertEqual(e.classify("On"), REJECT)
        e.assign(ACCEPT)
        self.assertEqual(e.classify("On"), ACCEPT)

    def test_exclusive(self):
        e = mk()  # ['Auto','Off','On'], current On
        e.cursor = e.values().index("Off")
        e.exclusive()
        self.assertEqual(e.classify("Off"), ACCEPT)
        for v in ("Auto", "On"):
            self.assertEqual(e.classify(v), REJECT, v)
        # unknown bucket emptied
        self.assertEqual(e.to_review().unknown, [])

    def test_exclusive_flip_keeps_all_values_and_cursor(self):
        # Starting: reject Disable, accept Enable. Flip exclusive the other way
        # twice (regression: values used to disappear + cursor went out of range).
        opt = ReviewOption(path="hp-x/Secure Boot", current="Enable",
                           accept=["Enable"], reject=["Disable"], unknown=[])
        e = ReviewEdit.from_review(opt)
        e.cursor = e.values().index("Disable")
        e.exclusive()
        self.assertEqual(e.values(), ["Disable", "Enable"])
        self.assertTrue(0 <= e.cursor < len(e.values()))
        e.cursor = e.values().index("Enable")
        e.exclusive()
        # The flipped-away value must not vanish from the list.
        self.assertEqual(e.values(), ["Disable", "Enable"])
        self.assertTrue(0 <= e.cursor < len(e.values()))
        self.assertEqual(e.classify("Enable"), ACCEPT)
        self.assertEqual(e.classify("Disable"), REJECT)
        # Pressing * again (nothing else selected) must not crash.
        e.exclusive()
        self.assertEqual(e.values(), ["Disable", "Enable"])

    def test_exclusive_empty_cursor_is_defensive(self):
        opt = ReviewOption(path="hp-x/Secure Boot", current="Enable",
                           accept=["Enable"], reject=["Disable"], unknown=[])
        e = ReviewEdit.from_review(opt)
        e.cursor = 99  # out of range (no valid selection)
        e.exclusive()  # must not raise
        e.assign(ACCEPT)  # must not raise
        self.assertEqual(e.to_review().accept, ["Enable"])

    def test_exclusive_on_single_value(self):
        opt = ReviewOption(path="hp-x/F", current="On",
                           accept=[], reject=[], unknown=["On"])
        e = ReviewEdit.from_review(opt)
        e.exclusive()
        self.assertEqual(e.classify("On"), ACCEPT)

    def test_reset_restores_original(self):
        e = mk()
        e.cursor = e.values().index("Auto")
        e.assign(REJECT)
        e.assign(REJECT)  # Auto -> reject
        e.exclusive()
        self.assertNotEqual(e.classify("Auto"), REJECT)
        e.reset()
        self.assertEqual(e.to_review().accept, ["On"])
        self.assertEqual(e.to_review().reject, [])
        self.assertEqual(sorted(e.to_review().unknown), ["Auto", "Off"])

    def test_to_review_roundtrip(self):
        e = mk(accepted=("A",), rejected=("B",), unknown=("C",))
        r = e.to_review()
        self.assertEqual(r.path, "hp-x/Foo")
        self.assertEqual(r.accept, ["A"])
        self.assertEqual(r.reject, ["B"])
        self.assertEqual(sorted(r.unknown), ["C"])
        self.assertEqual(r.current, "On")


class ReviewEditSerializationTest(unittest.TestCase):
    def test_save_review_accepts_edits(self):
        import tempfile, os
        from uefi_policy.policy import load_review
        e = mk(accepted=("A",), rejected=("B",))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            save_review([e.to_review()], path)
            loaded = load_review(path)[0]
            self.assertEqual(loaded.accept, ["A"])


if __name__ == "__main__":
    unittest.main()
