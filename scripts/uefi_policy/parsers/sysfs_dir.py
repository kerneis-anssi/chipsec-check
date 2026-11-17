"""Parser for a sysfs firmware-attributes directory tree.

Given a directory that is ``/sys/class/firmware-attributes`` (or a copy of it),
descend the tree to read the attributes of every BIOS option:

    <root>/<vendor>/attributes/<option>/<attribute-file>

Only the ``attributes`` class is parsed (the same rule the fwupd JSON format
follows); other classes such as ``authentication``/``power`` are skipped, and
plain files directly under ``attributes`` (e.g. the module-level
``pending_reboot`` scalar) are ignored.

The model mirrors the fwupd JSON parser so both structured sources produce
identical policy keys:
- an option with a ``possible_values``/``elements`` file is an ``enumeration``
- anything else is a ``string``

The policy key is built from the on-disk ``<vendor>/attributes/<option>`` path:
strip the ``/attributes/`` class segment, then undo HP's FAT32-safe
``!`` → ``/`` escape (e.g. ``hp-bioscfg/Save!Restore GPT ...`` →
``hp-bioscfg/Save/Restore GPT ...``).
"""

from __future__ import annotations

import os
from typing import List

from uefi_policy.model import Option
from uefi_policy.parsers.base import BaseParser

_CLASS = "attributes"

# Fields that are not option metadata but map onto the Option model.
_VALUE_FIELDS = ("current_value",)
_ENUM_VALUE_FIELDS = ("possible_values", "elements")


def _canonical(text: str) -> str:
    """Replace HP's FAT32-safe ``!`` escape back to ``/`` for canonical names."""
    return text.replace("!", "/")


def _read_file(path: str) -> str:
    """Read a small attribute file as text, stripping trailing whitespace."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().rstrip("\r\n")


class SysfsDirParser(BaseParser):
    """Descend ``<root>/<vendor>/attributes/*`` and read options."""

    def parse(self, source: str) -> List[Option]:
        root = source
        if not os.path.isdir(root):
            raise ValueError(
                f"sysfs-dir input is not a directory: {root!r} "
                "(expected /sys/class/firmware-attributes or a copy)"
            )
        options: List[Option] = []
        for vendor in sorted(os.listdir(root)):
            vendor_dir = os.path.join(root, vendor)
            if not os.path.isdir(vendor_dir):
                continue
            attrs_dir = os.path.join(vendor_dir, _CLASS)
            if not os.path.isdir(attrs_dir):
                continue
            for entry in sorted(os.listdir(attrs_dir)):
                entry_path = os.path.join(attrs_dir, entry)
                if not os.path.isdir(entry_path):
                    # Plain file directly under attributes (e.g. pending_reboot):
                    # a module-level scalar, not an option; skip it.
                    continue
                options.append(self._parse_option(vendor, entry, entry_path))
        return options

    def _parse_option(self, vendor: str, optname: str, dirpath: str) -> Option:
        fields: dict = {}
        for attr in sorted(os.listdir(dirpath)):
            attr_path = os.path.join(dirpath, attr)
            if not os.path.isfile(attr_path):
                continue
            try:
                fields[attr] = _read_file(attr_path)
            except OSError:
                # Unreadable sysfs node; carry on with the rest.
                continue

        current_value = fields.get("current_value")
        possible = None
        optype = None
        for ek in _ENUM_VALUE_FIELDS:
            if ek in fields:
                optype = "enumeration"
                possible = [v.strip() for v in fields[ek].split(";") if v.strip()]
                break
        if optype is None:
            optype = "string"

        metadata = {k: v for k, v in fields.items()
                    if k not in _VALUE_FIELDS and k not in _ENUM_VALUE_FIELDS}

        raw_path = f"{vendor}/{_CLASS}/{optname}"
        return Option(
            path=self._canonical_path(vendor, optname),
            name=_canonical(optname),
            type=optype,
            possible_values=possible or None,
            current_value=current_value,
            metadata=metadata,
            raw_path=raw_path,
        )

    @staticmethod
    def _canonical_path(vendor: str, optname: str) -> str:
        return _canonical(f"{vendor}/{optname}")
