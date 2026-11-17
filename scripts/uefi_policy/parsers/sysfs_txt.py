"""Parser for the ``grep -R . /sys/class/firmware-attributes/`` text dump.

Only real configuration options are kept: those living under the Linux
``<vendor>/attributes/`` class. Non-option data that HP exposes under other
classes (e.g. ``authentication/...``, ``power/...``) is discarded.

Each line has the form ``<vendor>/attributes/<option>/<key>:<value>``. Because
option names and values may themselves contain ``/`` or ``:``, the field key is
a known identifier and the line is split on the rightmost ``/<key>:`` boundary.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from uefi_policy.model import Option
from uefi_policy.parsers.base import BaseParser

# Keys that represent the "value" of an enumeration/ordered-list.
_ENUM_VALUE_KEYS = ("possible_values", "elements")
_META_EXCLUDED_KEYS = ("type", "current_value") + _ENUM_VALUE_KEYS

# HP exposes `/` in option names as `!` in the sysfs dump because `/` is
# forbidden in filenames. The canonical name uses `/` so both the sysfs dump
# and the HP Setup report reconcile to the same identity.
_FAT32_ESCAPE = "!"

# Field names that appear on options under ``attributes``. The key is always one
# of these lowercase identifiers, so we split on the rightmost ``/<key>:``.
# (Keys belonging only to the discarded authentication/power classes are absent.)
_KNOWN_KEYS = (
    "possible_values", "current_value", "display_name", "display_name_language_code",
    "min_length", "max_length", "lower_bound", "upper_bound", "scalar_increment",
    "elements", "audit_log_entry_count", "type",
)


def _canonical(text: str) -> str:
    """Replace HP's FAT32-safe ``!`` escape back to ``/`` for canonical names."""
    return text.replace(_FAT32_ESCAPE, "/")


def _find_key_boundary(line: str) -> Tuple[str, str, int]:
    """Find the field key on a line: returns (key, value, path_start).

    The key is a known field name; the boundary is the rightmost ``/<key>:``
    in the line. Returns (None, '', 0) if no known key is present (the line is
    not a recognized option attribute and should be skipped)."""
    best_key = None
    best_start = -1
    for key in _KNOWN_KEYS:
        idx = line.rfind("/" + key + ":")
        if idx > best_start:
            best_start = idx
            best_key = key
    if best_key is None:
        return None, "", 0
    key_end = best_start + 1 + len(best_key) + 1  # just after ':'
    return best_key, line[key_end:], best_start


def _split_key_value(line: str) -> Tuple[str | None, str, str]:
    """Split a line into (path, key, value). Any of these may be None/empty if
    the line has no recognized field key."""
    key, value, start = _find_key_boundary(line)
    if key is None:
        return None, "", ""
    return line[:start], key, value


class SysfsTxtParser(BaseParser):
    def __init__(self, kept_class: str = "attributes"):
        self.kept_class = kept_class

    def parse(self, source: str) -> List[Option]:
        grouped: Dict[str, Dict[str, str]] = {}
        order: List[str] = []
        last_path_key: Tuple[str, str] | None = None

        def ensure(path: str):
            if path not in grouped:
                grouped[path] = {}
                order.append(path)

        for line in source.splitlines():
            if not line.strip():
                continue
            # Cheap pre-filter: only consider options under the kept class.
            # (Runs before key detection, which only knows the kept class's keys.)
            if "/" + self.kept_class + "/" not in line:
                continue
            path, key, value = _split_key_value(line)
            if not path or not key:
                continue
            # Keep only real options under vendor/<kept_class>/<option>.
            segs = path.split("/")
            if len(segs) < 3 or segs[1] != self.kept_class:
                continue
            ensure(path)
            if last_path_key == (path, key):
                # Same key again: continuation of a multi-line value. Join all
                # consecutive lines for a given (path, key) regardless of format
                # (works even if the value is not valid JSON).
                grouped[path][key] += "\n" + value
            else:
                grouped[path][key] = value
            last_path_key = (path, key)

        options: List[Option] = []
        for path in order:
            meta = grouped[path]
            cur_type = meta.get("type")
            current_value = meta.get("current_value")

            possible_values: List[str] = []
            for ek in _ENUM_VALUE_KEYS:
                if ek in meta:
                    possible_values = [v.strip() for v in meta[ek].split(";") if v.strip()]
                    break

            name = self._canonical_name(meta.get("display_name") or path.rsplit("/", 1)[-1] or path)
            metadata = {k: v for k, v in meta.items() if k not in _META_EXCLUDED_KEYS}

            options.append(
                Option(
                    path=self._normalize(path),
                    name=name,
                    type=cur_type,
                    possible_values=possible_values or None,
                    current_value=current_value,
                    metadata=metadata,
                    raw_path=path,
                )
            )
        return options

    def _normalize(self, path: str) -> str:
        """Strip the kept class segment from the identity key.

        A raw path ``hp-bioscfg/attributes/Secure Boot`` maps to the policy key
        ``hp-bioscfg/Secure Boot``.
        """
        parts = path.split("/")
        if len(parts) >= 2 and parts[1] == self.kept_class:
            parts = parts[:1] + parts[2:]
        return _canonical("/".join(parts))

    def _canonical_name(self, path: str) -> str:
        """The human-friendly option name with FAT32-safe escapes undone."""
        return _canonical(path)
