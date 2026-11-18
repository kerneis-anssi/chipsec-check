"""Core edit logic for interactive ``policy review``.

This module is deliberately terminal-independent so the edit semantics can be
unit-tested without a TTY. :class:`ReviewEdit` holds the mutable accept/reject/
unknown classification for a single option plus the current highlight cursor.
The curses loop lives in :mod:`uefi_policy.review_ui`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from uefi_policy.policy import ReviewOption

# Classification sets (also used as key-action names).
ACCEPT = "accept"
REJECT = "reject"
UNKNOWN = "undecided"  # the "unknown/waiting" bucket


@dataclass
class ReviewEdit:
    """Editable review state for a single option key."""

    path: str
    current: Optional[str]
    _accept: set = field(default_factory=set)
    _reject: set = field(default_factory=set)
    _unknown: set = field(default_factory=set)
    cursor: int = 0
    _orig: Optional[ReviewOption] = field(default=None, repr=False)

    @classmethod
    def from_review(cls, opt: ReviewOption) -> "ReviewEdit":
        e = cls(
            path=opt.path,
            current=opt.current,
            _accept=set(opt.accept),
            _reject=set(opt.reject),
            _unknown=set(opt.unknown),
            _orig=opt,
        )
        e._init_cursor()
        return e

    @property
    def is_wildcard(self) -> bool:
        return bool(self._orig is not None and self._orig.wildcard)

    def _init_cursor(self) -> None:
        if self.current is not None:
            try:
                self.cursor = self.values().index(self.current)
                return
            except ValueError:
                pass
        self.cursor = 0

    # -- state queries -----------------------------------------------------

    def values(self) -> List[str]:
        """Alphabetical list of every value under this key."""
        vals = set(self._accept) | set(self._reject) | set(self._unknown)
        if self.current is not None:
            vals.add(self.current)
        return sorted(vals)

    def classify(self, value: str) -> str:
        """Return ACCEPT, REJECT or UNKNOWN for *value*."""
        if value in self._accept:
            return ACCEPT
        if value in self._reject:
            return REJECT
        return UNKNOWN

    # -- cursor movement ---------------------------------------------------

    def move_up(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def move_down(self) -> None:
        self.cursor = min(self._count() - 1, self.cursor + 1)

    def _count(self) -> int:
        return len(self.values())

    # -- edit operations ---------------------------------------------------

    def assign(self, target: str) -> None:
        """Move the highlighted value into the given set (accept/reject/undecided)."""
        value = self.values()[self.cursor]
        for s in (self._accept, self._reject, self._unknown):
            s.discard(value)
        if target == ACCEPT:
            self._accept.add(value)
        elif target == REJECT:
            self._reject.add(value)
        else:
            self._unknown.add(value)

    def exclusive(self) -> None:
        """Accept exactly the highlighted value; reject everything else."""
        value = self.values()[self.cursor]
        self._accept = {value}
        self._reject = set(self.values()) - {value}
        self._unknown = set()

    def reset(self) -> None:
        """Restore this option to its on-disk state (the original snapshot)."""
        if self._orig is None:
            return
        self._accept = set(self._orig.accept)
        self._reject = set(self._orig.reject)
        self._unknown = set(self._orig.unknown)
        self.current = self._orig.current
        self._init_cursor()

    # -- serialization -----------------------------------------------------

    def to_review(self) -> ReviewOption:
        return ReviewOption(
            path=self.path,
            accept=sorted(self._accept),
            reject=sorted(self._reject),
            unknown=sorted(self._unknown),
            current=self.current,
        )
