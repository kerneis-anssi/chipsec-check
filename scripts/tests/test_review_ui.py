"""Tests for the curses UI layer of ``policy review`` (driven by a fake screen)."""

import os
import tempfile
import unittest

from uefi_policy.policy import ReviewOption, load_review, save_review
from uefi_policy.review import ReviewEdit
from uefi_policy.review_ui import run as run_review


class FakeScreen:
    """Minimal curses-window stand-in that yields a scripted key sequence."""

    def __init__(self, keys):
        self._keys = list(keys)

    def getch(self):
        if not self._keys:
            raise EOFError("no more keys")
        return self._keys.pop(0)

    def getmaxyx(self):
        return (24, 80)

    def erase(self):
        pass

    def addnstr(self, *a):
        pass

    def addstr(self, *a):
        pass

    def refresh(self):
        pass


def edits_from(path):
    return [ReviewEdit.from_review(o) for o in load_review(path)]


class ReviewRunTest(unittest.TestCase):
    def _write(self, d, name="review.json", current="On",
               accepted=("On",), rejected=(), unknown=("Auto", "Off")):
        path = os.path.join(d, name)
        save_review([ReviewOption(path="hp-x/Foo", current=current,
                                  accept=list(accepted), reject=list(rejected),
                                  unknown=list(unknown))], path)
        return path

    def test_q_saves_changes(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d)
            # values [Auto, Off, On], cursor on "On". Reject "On", then save.
            result = run_review(edits_from(path), path, FakeScreen([ord("-"), ord("q"), ord("\n")]))
            self.assertTrue(result)
            saved = load_review(path)[0]
            self.assertEqual(saved.reject, ["On"])

    def test_x_discards_with_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d)
            result = run_review(edits_from(path), path, FakeScreen([ord("-"), ord("x"), ord("y")]))
            self.assertFalse(result)
            saved = load_review(path)[0]
            self.assertEqual(saved.reject, [])  # unchanged
            self.assertEqual(sorted(saved.unknown), ["Auto", "Off"])

    def test_esc_resets_current_option(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d)
            # accept Auto, then ESC, then save -> original state preserved.
            result = run_review(edits_from(path), path,
                                FakeScreen([ord("j"), ord("+"), 27, ord("q"), ord("\n")]))
            self.assertTrue(result)
            saved = load_review(path)[0]
            self.assertEqual(sorted(saved.accept), ["On"])  # "Auto" discarded by ESC
            self.assertEqual(sorted(saved.unknown), ["Auto", "Off"])

    def test_navigates_between_options_and_discard_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            save_review([
                ReviewOption(path="hp-x/One", current="A", accept=["A"], unknown=["B"]),
                ReviewOption(path="hp-x/Two", current="C", reject=["C"], unknown=["D"]),
            ], path)
            edits = edits_from(path)
            # move to option 2 (n), reject 'D', then discard quit (x then y);
            # the first x+n aborts the confirm, second confirms.
            keys = [ord("n"), ord("j"), ord("-"), ord("x"), ord("n"), ord("x"), ord("y")]
            result = run_review(edits, path, FakeScreen(keys))
            self.assertFalse(result)
            saved = {o.path: o for o in load_review(path)}
            self.assertEqual(saved["hp-x/Two"].reject, ["C"])  # unchanged

    def _two_options(self, d):
        path = os.path.join(d, "review.json")
        save_review([
            ReviewOption(path="hp-x/One", current="A", accept=["A"], unknown=["B"]),
            ReviewOption(path="hp-x/Two", current="C", reject=["C"], unknown=["D"]),
        ], path)
        return path

    def test_q_saves_progress(self):
        from uefi_policy.policy import review_progress, save_review
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d)
            result = run_review(edits_from(path), path,
                                FakeScreen([ord("-"), ord("q"), ord("\n")]))
            self.assertTrue(result)
            self.assertEqual(review_progress(path), "hp-x/Foo")

    def test_start_path_jumps_to_option_and_progress_reflects_it(self):
        from uefi_policy.policy import review_progress
        with tempfile.TemporaryDirectory() as d:
            path = self._two_options(d)
            edits = edits_from(path)
            result = run_review(edits, path, FakeScreen([ord("q"), ord("\n")]),
                                start_path="hp-x/Two")
            self.assertTrue(result)
            self.assertEqual(review_progress(path), "hp-x/Two")

    def test_n_on_last_confirms_save(self):
        from uefi_policy.policy import review_progress, load_review
        with tempfile.TemporaryDirectory() as d:
            path = self._two_options(d)
            edits = edits_from(path)
            # n -> Two (last); n again -> confirm; y -> save & quit.
            result = run_review(edits, path, FakeScreen([ord("n"), ord("n"), ord("y"), ord("\n")]))
            self.assertTrue(result)
            self.assertEqual(review_progress(path), "hp-x/Two")

    def test_n_on_last_reject_confirms_wraps_to_first(self):
        from uefi_policy.policy import review_progress
        with tempfile.TemporaryDirectory() as d:
            path = self._two_options(d)
            edits = edits_from(path)
            # n -> Two; n again -> confirm; 'N' rejects -> wrap to first; q -> save.
            keys = [ord("n"), ord("n"), ord("N"), ord("q"), ord("\n")]
            result = run_review(edits, path, FakeScreen(keys))
            self.assertTrue(result)
            self.assertEqual(review_progress(path), "hp-x/One")

    def test_p_wraps_to_last(self):
        from uefi_policy.policy import review_progress
        with tempfile.TemporaryDirectory() as d:
            path = self._two_options(d)
            edits = edits_from(path)
            # 'p' on the first option wraps to the last.
            result = run_review(edits, path, FakeScreen([ord("p"), ord("q"), ord("\n")]))
            self.assertTrue(result)
            self.assertEqual(review_progress(path), "hp-x/Two")

    def test_wildcard_entry_skipped_and_preserved_on_save(self):
        from uefi_policy.policy import load_review
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            save_review([
                ReviewOption(path="hp-x/Wild", accept=[], reject=[], wildcard=True),
                ReviewOption(path="hp-x/Real", current="A", accept=["A"], unknown=["B"]),
            ], path)
            edits = edits_from(path)
            self.assertEqual([e.path for e in edits if e.is_reviewable], ["hp-x/Real"])
            # Skip to the only reviewable option; save.
            result = run_review(edits, path, FakeScreen([ord("q"), ord("\n")]))
            self.assertTrue(result)
            saved = {o.path: o for o in load_review(path)}
            self.assertTrue(saved["hp-x/Wild"].wildcard)  # preserved
            self.assertEqual(saved["hp-x/Real"].accept, ["A"])


if __name__ == "__main__":
    unittest.main()
