"""Parser for HP ``HPSetup.txt`` style reports.

This is a host-generated report of the currently applied BIOS settings. It is a
plain text list: option name lines, each followed by one or more indented
(tab) value lines. For a selectable/enumeration option every possible value is
listed and the *applied* value is prefixed with ``*``:

    Secure Boot
        Disable
        *Enable

Options with a single value line and no ``*`` are scalar settings
(e.g. ``Product Name`` or a version number).

Semantics inferred:
- any ``*``-prefixed value            -> enumeration (possible_values + current)
- a single value line, no ``*``        -> scalar (string/integer) current
- multiple value lines, no ``*``       -> ordered-list: the values are the
  ``elements``/possible_values and the current value is their ``;``-joined
  form (matching the sysfs dump, where an ordered list's current_value equals
  its elements joined by ``;``).

There is no vendor/class prefix in this format, so options are namespaced
under ``hp-bioscfg/`` to align with the sysfs-derived policy keys.
"""

from __future__ import annotations

from typing import List

from uefi_policy.model import Option
from uefi_policy.parsers.base import BaseParser

_ENUM_VALUE_JOIN = ";"


class HPSetupTxtParser(BaseParser):
    def __init__(self, namespace: str = "hp-bioscfg"):
        self.namespace = namespace.rstrip("/")

    def parse(self, source: str) -> List[Option]:
        # Tolerate CRLF and trailing NULs; keep leading whitespace so tab-indented
        # value lines can be told apart from option name lines.
        raw_lines = [l.rstrip("\r\n\x00") for l in source.splitlines()]

        options: List[Option] = []
        name: str | None = None
        values: List[str] = []

        def flush():
            if name is None:
                return
            option = _build_option(self.namespace, name, values)
            if option is not None:
                options.append(option)

        for line in raw_lines:
            if not line.strip():
                continue
            if line[0] in "\t ":
                if name is not None:
                    values.append(line.strip())
                continue
            # A new option name line.
            flush()
            name = line.strip()
            values = []

        flush()
        return options


def _build_option(namespace: str, name: str, values: List[str]):
    starred = [v for v in values if v.startswith("*")]
    unmarked = [v[1:] if v.startswith("*") else v for v in values]

    if starred:
        current = starred[0][1:]
        possible = _dedup(unmarked)
        return Option(
            path=f"{namespace}/{name}",
            name=name,
            type="enumeration",
            possible_values=possible,
            current_value=current,
        )
    if len(values) == 1:
        # Scalar setting.
        val = values[0]
        return Option(
            path=f"{namespace}/{name}",
            name=name,
            type="integer" if val.isdigit() else "string",
            possible_values=None,
            current_value=val or None,
        )
    if len(values) > 1:
        # Ordered list: values are the possible elements; current is the joined
        # list (mirrors the sysfs dump semantics).
        return Option(
            path=f"{namespace}/{name}",
            name=name,
            type="ordered-list",
            possible_values=_dedup(unmarked),
            current_value=_ENUM_VALUE_JOIN.join(unmarked),
        )
    return None


def _dedup(values: List[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
