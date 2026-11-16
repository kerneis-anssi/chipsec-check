"""Input parsers: register the built-in parsers and expose a factory.

New source representations (e.g. an HP text format) are added by creating a
parser class and registering it here.
"""

from __future__ import annotations

from uefi_policy.parsers.base import BaseParser, available, create, register
from uefi_policy.parsers.sysfs_txt import SysfsTxtParser

register("sysfs-txt", SysfsTxtParser)

__all__ = ["BaseParser", "available", "create", "register"]
