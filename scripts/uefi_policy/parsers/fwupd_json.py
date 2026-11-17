"""Parser for fwupd JSON BIOS-settings output (``get-bios-settings``).

fwupd can dump the same firmware-attribute content in structured JSON, e.g.:

    {
      "BiosSettings": [
        {
          "Name": "Adaptive Battery Optimizer",
          "Filename": "/sys/class/firmware-attributes/hp-bioscfg/attributes/Adaptive Battery Optimizer",
          "BiosSettingCurrentValue": "Enable",
          "BiosSettingPossibleValues": ["Disable", "Enable"],
          "BiosSettingType": 1,
          ...
        }
      ]
    }

Each entry identifies the option through a `Filename` that mirrors the sysfs
path (`.../firmware-attributes/<vendor>/<class>/<option>`). From it we derive
the same canonical policy key used by the other parsers: strip the sysfs
prefix and the always-present `/attributes/` class, then undo HP's FAT32-safe
`!` → `/` escape.

Only two types exist in this format: an option with a `BiosSettingPossibleValues`
list is an ``enumeration``; anything else is a ``string``.
"""

from __future__ import annotations

import json
from typing import List, Optional

from uefi_policy.model import Option
from uefi_policy.parsers.base import BaseParser

_SYSFS_PREFIX = "/sys/class/firmware-attributes/"

_TYPE_ENUM = "enumeration"
_TYPE_STRING = "string"


def _canonical(text: str) -> str:
    """Replace HP's FAT32-safe ``!`` escape back to ``/`` for canonical names."""
    return text.replace("!", "/")


def _parse_fd(d: dict) -> Option:
    """Build an Option from one fwupd BiosSettings record."""
    name = d.get("Name") or d.get("BiosSettingId") or ""
    fields = ["BiosSettingCurrentValue", "BiosSettingPossibleValues", "BiosSettingType",
              "BiosSettingReadOnly", "BiosSettingFilename", "BiosSettingId",
              "BiosSettingLowerBound", "BiosSettingUpperBound"]
    metadata = {k: d[k] for k in fields if k in d}
    metadata["Description"] = d.get("Description")
    metadata = {k: v for k, v in metadata.items() if v is not None}

    if d.get("BiosSettingPossibleValues"):
        optype = _TYPE_ENUM
        possible = list(d["BiosSettingPossibleValues"])
    else:
        optype = _TYPE_STRING
        possible = None

    current = d.get("BiosSettingCurrentValue")
    raw = _raw_path(d)

    return Option(
        path=_canonical_path(raw, name),
        name=name,
        type=optype,
        possible_values=possible,
        current_value=current,
        metadata=metadata,
        raw_path=raw,
    )


def _raw_path(d: dict) -> Optional[str]:
    """The source path for the option, e.g. ``hp-bioscfg/attributes/Name``.

    Prefers the `Filename` (analogous to the sysfs path) and falls back to the
    `Name` for records that omit it.
    """
    filename = d.get("Filename")
    if filename:
        if filename.startswith(_SYSFS_PREFIX):
            return filename[len(_SYSFS_PREFIX):]
        return filename.lstrip("/")
    return d.get("Name")


def _canonical_path(raw: Optional[str], name: str) -> str:
    """Map a raw source path to the canonical policy key.

    Strip the always-present ``/attributes/`` class segment (vendor-specific
    segments like ``authentication``/``power`` are preserved) and undo the
    ``!`` → ``/`` escape, producing e.g. ``hp-bioscfg/Secure Boot``.
    """
    if raw:
        parts = raw.split("/")
        if len(parts) >= 2 and parts[1] == "attributes":
            parts = parts[:1] + parts[2:]
        return _canonical("/".join(parts))
    return _canonical(name)


class FwupdJsonParser(BaseParser):
    def parse(self, source: str) -> List[Option]:
        data = json.loads(source)
        settings = data.get("BiosSettings") if isinstance(data, dict) else None
        if not isinstance(settings, list):
            raise ValueError(
                "fwupd JSON has no 'BiosSettings' list; expected get-bios-settings output"
            )
        return [_parse_fd(d) for d in settings]
