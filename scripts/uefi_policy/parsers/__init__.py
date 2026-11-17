"""Input parsers: register the built-in parsers and expose a factory.

New source representations (e.g. an HP text format) are added by creating a
parser class and registering it here.
"""

from __future__ import annotations

from uefi_policy.parsers.base import BaseParser, available, create, register
from uefi_policy.parsers.fwupd_json import FwupdJsonParser
from uefi_policy.parsers.hpsetup_txt import HPSetupTxtParser

register("fwupd-json", FwupdJsonParser)
register("hp-setup", HPSetupTxtParser)


def detect(content: str) -> BaseParser:
    """Pick a parser from the raw text of a dump."""
    stripped = content.lstrip("\ufeff \t\r\n")
    # fwupd get-bios-settings output is a JSON object with a 'BiosSettings' list.
    if stripped.startswith("{"):
        return create("fwupd-json")
    # Otherwise it is an HP Setup report (bare option names with tab-indented,
    # possibly `*`-marked value lines).
    return create("hp-setup")


__all__ = ["BaseParser", "available", "create", "register", "detect"]
