"""Curses terminal UI for ``policy review``.

Thin key dispatching over :class:`uefi_policy.review.ReviewEdit`. ``run()``
accepts any curses-compatible screen object so it can be driven by a fake in
tests (no real TTY needed).
"""

from __future__ import annotations

import curses
from typing import List, Optional

from uefi_policy.policy import save_review
from uefi_policy.review import ACCEPT, REJECT, UNKNOWN, ReviewEdit

_REGION = ("n/p: option   j/k/\u2191\u2193: value   +: accept  -: reject  "
           "space: undecided  *: exclusive  ESC: reset  q: save & quit  x: discard")


def run(edits: List[ReviewEdit], path: str, stdscr) -> bool:
    """Interactive curses loop over *edits*. Returns True if saved, else False.

    *stdscr* is a curses window object (or a compatible fake in tests). Keys:
      n/p (or Left/Right)      - previous/next option
      j/k (or Down/Up)         - move highlight within the value list
      + / - / space            - accept / reject / undecide highlighted value
      *                        - accept highlighted exclusively (reject the rest)
      ESC                      - reset the current option to its on-disk state
      q                        - save changes and quit
      x                        - discard changes and quit (after confirmation)
    """
    try:
        curses.curs_set(0)
    except Exception:
        pass
    _focus(edits[0])
    target = 0
    while True:
        _render(stdscr, edits, target, None)
        key = stdscr.getch()

        if key == ord("q"):
            save_review([e.to_review() for e in edits], path)
            _flash(stdscr, f"Saved {len(edits)} options to {path}")
            stdscr.getch()
            return True
        if key == ord("x"):
            if _confirm(stdscr, "Discard changes and quit? (y/N)"):
                return False
            continue
        if key in (ord("n"), curses.KEY_RIGHT):
            target = min(target + 1, len(edits) - 1)
        elif key in (ord("p"), curses.KEY_LEFT):
            target = max(target - 1, 0)
        elif key in (curses.KEY_DOWN, ord("j")):
            edits[target].move_down()
        elif key in (curses.KEY_UP, ord("k")):
            edits[target].move_up()
        elif key == ord("+"):
            edits[target].assign(ACCEPT)
        elif key == ord("-"):
            edits[target].assign(REJECT)
        elif key == ord(" "):
            edits[target].assign(UNKNOWN)
        elif key == ord("*"):
            edits[target].exclusive()
        elif key == 27:  # ESC
            edits[target].reset()


def _focus(edit: ReviewEdit) -> None:
    """Clamp the cursor into range after constructing/resetting an option."""
    if edit.cursor > edit._count() - 1:
        edit.cursor = max(0, edit._count() - 1)


def _render(stdscr, edits: List[ReviewEdit], target: int, msg: Optional[str]) -> None:
    edit = edits[target]
    h, w = stdscr.getmaxyx()
    stdscr.erase()

    title = f"Reviewing {edit.path}   [{target + 1}/{len(edits)}]"
    _write(stdscr, 0, 0, title, w)
    if edit.current is not None:
        _write(stdscr, 1, 0, f"current: {edit.current}", w)

    row = 3
    for i, value in enumerate(edit.values()):
        line = _prefix(edit.classify(value)) + value
        if i == edit.cursor:
            stdscr.addnstr(row, 0, line[: w - 1], curses.A_REVERSE)
        else:
            stdscr.addnstr(row, 0, line[: w - 1])
        row += 1
        if row >= h - 2:
            break

    _write(stdscr, h - 1, 0, _REGION[: w - 1], w)
    if msg:
        _write(stdscr, h - 2, 0, msg[: w - 1], w)
    stdscr.refresh()


def _prefix(membership: str) -> str:
    """Prefix used to render a value: + accepted, - rejected, space otherwise."""
    if membership == ACCEPT:
        return "+ "
    if membership == REJECT:
        return "- "
    return "  "


def _write(stdscr, y: int, x: int, text: str, width: int) -> None:
    try:
        stdscr.addnstr(y, x, text[: width - 1])
    except curses.error:
        pass


def _flash(stdscr, text: str) -> None:
    try:
        h, w = stdscr.getmaxyx()
        stdscr.addnstr(h - 2, 0, text[: w - 1], curses.A_BOLD)
        stdscr.refresh()
    except curses.error:
        pass


def _confirm(stdscr, prompt: str) -> bool:
    _flash(stdscr, prompt)
    while True:
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (ord("n"), ord("N"), 27, ord("\n"), ord(" ")):
            return False
