"""Parser for the ``grep -R . /sys/class/firmware-attributes/`` text dump.

Each line has the form ``<prefix>/<option>/<key>:<value>``. Because option
names and values may themselves contain colons, the line is split on the LAST
``/`` to separate the option path from ``<key>:<value>``.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from uefi_policy.model import Option
from uefi_policy.parsers.base import BaseParser

# Keys that represent the "value" of an enumeration/ordered-list.
_ENUM_VALUE_KEYS = ("possible_values", "elements")
_META_EXCLUDED_KEYS = ("type", "current_value") + _ENUM_VALUE_KEYS

# Field names that appear in a dump line as ``<option>/<key>:<value>``. The key
# is always one of these lowercase identifiers, so we split on the rightmost
# ``/<key>:`` boundary. This is robust against option names and values that
# themselves contain ``/`` or ``:``.
_KNOWN_KEYS = (
    "possible_values", "current_value", "display_name", "display_name_language_code",
    "min_length", "max_length", "lower_bound", "upper_bound", "scalar_increment",
    "elements", "audit_log_entry_count", "control", "encodings", "is_enabled",
    "key_mechanism", "mechanism", "min_password_length", "max_password_length",
    "pending_reboot", "role", "runtime_active_time", "runtime_status",
    "runtime_suspended_time", "status", "type",
)


def _continues(value: str) -> bool:
    """True if a raw value appears to continue on the next line.

    Used to reassemble multi-line values (e.g. the ``status`` JSON blob, which
    grep emits over several physical lines). A value is "incomplete" when it
    has more opening than closing brace/bracket/paren characters.
    """
    opens = sum(value.count(c) for c in "[{(")
    closes = sum(value.count(c) for c in "]})")
    return opens > closes


def _find_key_boundary(line: str) -> Tuple[str, str, int]:
    """Find the field key on a line: returns (key, value, path_start).

    The key is a known field name; the boundary is the rightmost ``/<key>:``
    in the line. Returns (key, value, index_of_path_start)."""
    best_key = None
    best_start = -1
    for key in _KNOWN_KEYS:
        idx = line.rfind("/" + key + ":")
        if idx > best_start:
            best_start = idx
            best_key = key
    if best_key is None:
        raise ValueError(f"no known field key found in line: {line!r}")
    key_end = best_start + 1 + len(best_key) + 1  # just after ':'
    return best_key, line[key_end:], best_start


def _split_key_value(line: str) -> Tuple[str, str, str]:
    """Split a line into (path, key, value).

    The key is a known field name; we split on the rightmost ``/<key>:`` so that
    option names and values containing ``/`` or ``:`` are handled correctly.
    """
    key, value, start = _find_key_boundary(line)
    return line[:start], key, value


class SysfsTxtParser(BaseParser):
    def __init__(self, strip_segments: tuple = ("attributes",)):
        self.strip_segments = tuple(strip_segments)

    def parse(self, source: str) -> List[Option]:
        lines = [l for l in source.splitlines() if l.strip()]
        raw: List[Tuple[str, str, str]] = []
        for line in lines:
            path, key, value = _split_key_value(line)
            if not key:
                # Not a well-formed key:value line; skip defensively.
                continue
            # Reassemble multi-line values sharing the same path+key.
            if (
                raw
                and raw[-1][0] == path
                and raw[-1][1] == key
                and _continues(raw[-1][2])
            ):
                merged_path, merged_key, merged_value = raw[-1]
                raw[-1] = (merged_path, merged_key, merged_value + "\n" + value)
            else:
                raw.append((path, key, value))

        # Group keys per option path, preserving first-seen order.
        grouped: Dict[str, Dict[str, str]] = {}
        order: List[str] = []
        for path, key, value in raw:
            if path not in grouped:
                grouped[path] = {}
                order.append(path)
            grouped[path][key] = value

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

            name = meta.get("display_name") or path.rsplit("/", 1)[-1] or path
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
        """Strip the always-present Linux class segment from the identity key.

        A raw path ``hp-bioscfg/attributes/Secure Boot`` maps to the policy key
        ``hp-bioscfg/Secure Boot``. Other class segments (e.g. ``authentication``,
        ``power``) are preserved.
        """
        parts = path.split("/")
        if len(parts) >= 2 and parts[1] in self.strip_segments:
            parts = parts[:1] + parts[2:]
        return "/".join(parts)
