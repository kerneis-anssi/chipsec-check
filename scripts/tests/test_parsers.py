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

    def test_non_attributes_class_preserved(self):
        options = parse_sample()
        # authentication/SPM is metadata only (no type):
        spm = next(o for o in options if "SPM" in o.path)
        self.assertIn("authentication", spm.path)
        self.assertIn("status", spm.metadata)

    def test_multiline_value_reassembled(self):
        options = parse_sample()
        spm = next(o for o in options if "SPM" in o.path)
        self.assertTrue(spm.metadata["status"].startswith("{"))
        self.assertTrue(spm.metadata["status"].endswith("}"))


if __name__ == "__main__":
    unittest.main()
