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


if __name__ == "__main__":
    unittest.main()
