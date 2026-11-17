"""Tests for the sysfs-txt parser."""

import os
import unittest

from uefi_policy.parsers import create

DATA = os.path.join(os.path.dirname(__file__), "data", "sample.txt")


def parse_sample():
    with open(DATA, encoding="utf-8") as fh:
        return create("sysfs-txt").parse(fh.read())


class SysfsTxtParserTest(unittest.TestCase):
    def test_parses_expected_options(self):
        options = parse_sample()
        paths = {o.path for o in options}
        self.assertIn("hp-bioscfg/Secure Boot", paths)
        self.assertIn("hp-bioscfg/Bluetooth", paths)
        self.assertIn("hp-bioscfg/TPM Device", paths)

    def test_class_segment_stripped(self):
        options = parse_sample()
        boot = next(o for o in options if o.path == "hp-bioscfg/Secure Boot")
        self.assertEqual(boot.raw_path, "hp-bioscfg/attributes/Secure Boot")
        self.assertEqual(boot.name, "Secure Boot")
        self.assertEqual(boot.type, "enumeration")
        self.assertEqual(boot.possible_values, ["Disable", "Enable"])
        self.assertEqual(boot.current_value, "Enable")

    def test_non_attributes_classes_discarded(self):
        options = parse_sample()
        paths = {o.path for o in options}
        # No authentication/... or power/... options are parsed at all.
        self.assertNotIn("hp-bioscfg/authentication/SPM", paths)
        self.assertNotIn("hp-bioscfg/power", paths)
        # Their keys did not leak into any option.
        for o in options:
            self.assertNotIn("role", o.metadata)
            self.assertNotIn("runtime_active_time", o.metadata)

    def test_class_level_scalar_discarded(self):
        # pending_reboot is a scalar directly under attributes (no option name),
        # not a real option; it should not appear.
        options = parse_sample()
        paths = {o.path for o in options}
        self.assertNotIn("hp-bioscfg/pending_reboot", paths)

    def test_multiline_value_reassembled(self):
        # A multi-line value under attributes is reassembled simply by joining
        # consecutive lines for the same key (no brace-balance needed).
        src = (
            "hp-bioscfg/attributes/Custom Cfg/current_value:line one\n"
            "hp-bioscfg/attributes/Custom Cfg/current_value:line two\n"
            "hp-bioscfg/attributes/Custom Cfg/current_value:line three\n"
        )
        options = create("sysfs-txt").parse(src)
        cfg = next(o for o in options if o.path == "hp-bioscfg/Custom Cfg")
        self.assertEqual(cfg.current_value, "line one\nline two\nline three")

    def test_fat32_escape_canonicalized(self):
        # A sysfs name using HP's `!` escape for `/` should map to `/`.
        src = ("hp-bioscfg/attributes/Save!Restore GPT of System Hard Drive/type:enumeration\n"
               "hp-bioscfg/attributes/Save!Restore GPT of System Hard Drive/current_value:Disabled\n")
        options = create("sysfs-txt").parse(src)
        self.assertEqual(options[0].path, "hp-bioscfg/Save/Restore GPT of System Hard Drive")
        self.assertEqual(options[0].name, "Save/Restore GPT of System Hard Drive")
        self.assertEqual(options[0].raw_path, "hp-bioscfg/attributes/Save!Restore GPT of System Hard Drive")


if __name__ == "__main__":
    unittest.main()
