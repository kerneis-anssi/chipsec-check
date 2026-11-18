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


def run(edits: List[ReviewEdit], path: str, stdscr, start_path: Optional[str] = None) -> bool:
    """Interactive curses loop over *edits*. Returns True if saved, else False.

    *stdscr* is a curses window object (or a compatible fake in tests). Keys:
      n/p (or Left/Right)      - next/previous option (p on the first wraps to
                                 the last; n on the last prompts to save & quit)
      j/k (or Down/Up)         - move highlight within the value list
      + / - / space            - accept / reject / undecide highlighted value
      *                        - accept highlighted exclusively (reject the rest)
      ESC                      - reset the current option to its on-disk state
      q                        - save changes and quit
      x                        - discard changes and quit (after confirmation)

    Only the option's ``progress`` marker is written on discard (its position);
    the review decisions are saved only on ``q`` / the save-confirm.
    """
    try:
        curses.curs_set(0)
    except Exception:
        pass
    # A lone ESC key would otherwise wait for a possible escape-sequence prefix,
    # making ESC laggy. Set the escape disambiguation delay to zero.
    try:
        curses.set_escdelay(0)
    except Exception:
        pass
    # Only options with a decision to make are navigable; the full *edits* list
    # (including wildcards / empty rows) is what gets persisted.
    acts = [i for i, e in enumerate(edits) if e.is_reviewable]
    if not acts:
        return True  # nothing to decide
    _focus(edits[acts[0]])
    target = 0
    if start_path is not None:
        for pos, i in enumerate(acts):
            if edits[i].path == start_path:
                target = pos
                break
    count = len(acts)

    while True:
        _render(stdscr, edits, acts[target], count, None)
        key = stdscr.getch()

        if key == ord("q"):
            _save_decisions(edits, acts[target], path)
            _flash(stdscr, f"Saved {len(edits)} options to {path}")
            stdscr.getch()
            return True
        if key == ord("x"):
            if _confirm(stdscr, "Discard changes and quit? (y/N)"):
                _save_progress_only(edits, acts[target], path)
                return False
            continue
        if key in (ord("n"), curses.KEY_RIGHT):
            if target == count - 1:
                if _confirm(stdscr, "This is the last option. Save and quit? (y/N)"):
                    _save_decisions(edits, acts[target], path)
                    _flash(stdscr, f"Saved {len(edits)} options to {path}")
                    stdscr.getch()
                    return True
                target = 0  # "no": wrap back to the first option
            else:
                target += 1
        elif key in (ord("p"), curses.KEY_LEFT):
            target = count - 1 if target == 0 else target - 1  # p wraps to last
        elif key in (curses.KEY_DOWN, ord("j")):
            edits[acts[target]].move_down()
        elif key in (curses.KEY_UP, ord("k")):
            edits[acts[target]].move_up()
        elif key == ord("+"):
            edits[acts[target]].assign(ACCEPT)
        elif key == ord("-"):
            edits[acts[target]].assign(REJECT)
        elif key == ord(" "):
            edits[acts[target]].assign(UNKNOWN)
        elif key == ord("*"):
            edits[acts[target]].exclusive()
        elif key == 27:  # ESC
            edits[acts[target]].reset()


def _save_decisions(edits: List[ReviewEdit], target_index: int, path: str) -> None:
    """Persist all edit state and the current option as the progress marker."""
    save_review([e.to_review() for e in edits], path, progress=edits[target_index].path)


def _save_progress_only(edits: List[ReviewEdit], target_index: int, path: str) -> None:
    """Persist only the progress marker, keeping the on-disk review decisions
    unchanged (used on discard)."""
    from uefi_policy.policy import load_review

    fresh = load_review(path)
    save_review(fresh, path, progress=edits[target_index].path)



def _focus(edit: ReviewEdit) -> None:
    """Clamp the cursor into range after constructing/resetting an option."""
    if edit.cursor > edit._count() - 1:
        edit.cursor = max(0, edit._count() - 1)


def _render(stdscr, edits: List[ReviewEdit], target: int, count: int, msg: Optional[str]) -> None:
    edit = edits[target]
    h, w = stdscr.getmaxyx()
    stdscr.erase()

    title = f"Reviewing {edit.path}   [{target + 1}/{count}]"
    _write(stdscr, 0, 0, title, w)
    if edit.current is not None:
        _write(stdscr, 1, 0, f"current: {edit.current}", w)

    row = 3
    width_lim = max(0, w - 1)
    for i, value in enumerate(edit.values()):
        line = _prefix(edit.classify(value)) + value
        if i == edit.cursor:
            stdscr.addnstr(row, 0, line, min(width_lim, len(line)), curses.A_REVERSE)
        else:
            stdscr.addnstr(row, 0, line, min(width_lim, len(line)))
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
        n = max(0, min(width - 1, len(text)))
        stdscr.addnstr(y, x, text, n)
    except curses.error:
        pass


def _flash(stdscr, text: str) -> None:
    try:
        h, w = stdscr.getmaxyx()
        stdscr.addnstr(h - 2, 0, text, max(0, min(w - 1, len(text))), curses.A_BOLD)
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
