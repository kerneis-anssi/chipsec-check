"""Core data structures for the UEFI policy analyzer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Status(str, Enum):
    """Evaluation status for an option."""

    OK = "OK"
    VIOLATION = "VIOLATION"
    UNKNOWN_OPTION = "UNKNOWN_OPTION"
    UNKNOWN_VALUE = "UNKNOWN_VALUE"
    IGNORED = "IGNORED"


@dataclass
class Option:
    """A single UEFI configuration option after parsing a source dump.

    Attributes:
        path: Normalized identity key used for policy lookup, e.g.
            ``hp-bioscfg/Secure Boot`` (the Linux ``/attributes/`` class segment
            has already been stripped).
        name: Human-friendly display name (from ``display_name`` if available,
            else the leaf segment of the raw path).
        type: Optional firmware attribute type (``enumeration``, ``integer``,
            ``ordered-list``, ``string``...). May be ``None`` for metadata rows.
        possible_values: Optional list of values/options the option can take
            (from ``possible_values`` or ``elements``).
        current_value: The current value, if any.
        metadata: All other keys captured from the dump, kept verbatim (e.g.
            ``min_length``, ``upper_bound``, ``display_name``).
        raw_path: The full unprefixed path as read (e.g.
            ``hp-bioscfg/attributes/Secure Boot``) for mapping back to sysfs.
    """

    path: str
    name: str
    type: Optional[str] = None
    possible_values: Optional[List[str]] = None
    current_value: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    raw_path: Optional[str] = None

    @property
    def is_policy_checkable(self) -> bool:
        """Whether this is a real option (has a type) rather than a pure
        metadata row. A typed option is handled even if it has no current value
        in the dump; only type-less rows are ignored."""
        return self.type is not None


@dataclass
class Result:
    """Evaluation result for a single option."""

    option: Option
    statuses: List[Status] = field(default_factory=list)

    @property
    def primary_status(self) -> Status:
        """Report which must surface in review."""
        if Status.VIOLATION in self.statuses:
            return Status.VIOLATION
        if Status.UNKNOWN_OPTION in self.statuses:
            return Status.UNKNOWN_OPTION
        if Status.UNKNOWN_VALUE in self.statuses:
            return Status.UNKNOWN_VALUE
        if Status.IGNORED in self.statuses:
            return Status.IGNORED
        return Status.OK
