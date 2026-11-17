"""Input parsers: register the built-in parsers and expose a factory.

New source representations (e.g. an HP text format) are added by creating a
parser class and registering it here.
"""

from __future__ import annotations

from uefi_policy.parsers.base import BaseParser, available, create, register
from uefi_policy.parsers.fwupd_json import FwupdJsonParser
from uefi_policy.parsers.hpsetup_txt import HPSetupTxtParser
from uefi_policy.parsers.sysfs_txt import SysfsTxtParser

register("sysfs-txt", SysfsTxtParser)
register("hp-setup", HPSetupTxtParser)
register("fwupd-json", FwupdJsonParser)


def detect(content: str) -> BaseParser:
    """Pick a parser from the raw text of a dump."""
    stripped = content.lstrip("\ufeff \t\r\n")
    # fwupd get-bios-settings output is a JSON object with a 'BiosSettings' list.
    if stripped.startswith("{"):
        return create("fwupd-json")
    # Sysfs dumps have lines like ``hp-bioscfg/attributes/Secure Boot/key:value``
    # (a ``/``-prefixed path and a ``:`` separator). The HP Setup report has
    # bare option names with tab-indented values and ``*`` markers. A sysfs
    # dump's first non-empty line is a leading-slash-free but slash-containing
    # path ending with ``:``.
    for line in content.splitlines():
        line = line.lstrip("\ufeff").strip()
        if not line or line.startswith("\t"):
            continue
        # sysfs: has a slash-path and a colon before any second-line value.
        if "/" in line and ":" in line:
            return create("sysfs-txt")
        # HP Setup: e.g. "Secure Boot" / "Product Name".
        return create("hp-setup")
    return create("hp-setup")


__all__ = ["BaseParser", "available", "create", "register", "detect"]
