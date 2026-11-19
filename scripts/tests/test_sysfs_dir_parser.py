"""Tests for the sysfs firmware-attributes directory parser."""

import os
import tempfile
import unittest
from unittest import mock

from uefi_policy.parsers import create

DATA = os.path.join(os.path.dirname(__file__), "data", "sysfs_dir")


def parse_sample():
    return create("sysfs-dir").parse(DATA)


class SysfsDirParserTest(unittest.TestCase):
    def test_parses_expected_options(self):
        options = parse_sample()
        paths = {o.path for o in options}
        self.assertIn("hp-bioscfg/Secure Boot", paths)
        self.assertIn("hp-bioscfg/Product Name", paths)
        self.assertIn("hp-bioscfg/Processor 1 Cache Size (L1/L2/L3)", paths)

    def test_enumeration(self):
        options = parse_sample()
        boot = next(o for o in options if o.path == "hp-bioscfg/Secure Boot")
        self.assertEqual(boot.type, "enumeration")
        self.assertEqual(boot.possible_values, ["Disable", "Enable"])
        self.assertEqual(boot.current_value, "Enable")
        self.assertEqual(boot.raw_path, "hp-bioscfg/attributes/Secure Boot")
        self.assertEqual(boot.name, "Secure Boot")

    def test_string_without_possible_values(self):
        options = parse_sample()
        product = next(o for o in options if o.path == "hp-bioscfg/Product Name")
        self.assertEqual(product.type, "string")
        self.assertIsNone(product.possible_values)
        self.assertEqual(product.current_value, "HP EliteBook 640")
        self.assertIn("encodings", product.metadata)  # non-model field kept verbatim

    def test_fat32_escape_canonicalized(self):
        options = parse_sample()
        gpt = next(o for o in options if "Restore GPT" in o.path)
        self.assertEqual(gpt.path, "hp-bioscfg/Save/Restore GPT of System Hard Drive")
        self.assertEqual(gpt.raw_path,
                         "hp-bioscfg/attributes/Save!Restore GPT of System Hard Drive")
        cache = next(o for o in options if "Cache Size" in o.path)
        self.assertEqual(cache.path, "hp-bioscfg/Processor 1 Cache Size (L1/L2/L3)")

    def test_non_attributes_class_and_scalar_skipped(self):
        options = parse_sample()
        paths = {o.path for o in options}
        # authentication class and the module-level pending_reboot scalar are not options.
        self.assertNotIn("hp-bioscfg/authentication/SPM", paths)
        for o in options:
            self.assertNotIn("role", o.metadata)
            self.assertNotIn("pending_reboot", o.metadata)

    def test_all_options_checkable(self):
        options = parse_sample()
        self.assertTrue(all(o.is_policy_checkable for o in options))

    def test_rejects_non_directory(self):
        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(ValueError):
                create("sysfs-dir").parse(fh.name)

    def test_unreadable_attribute_recorded_as_denied(self):
        # Force _read_file to raise OSError for the current_value file so the
        # parser must record the denial rather than silently dropping it.
        boot_attr = os.path.join(DATA, "hp-bioscfg", "attributes", "Secure Boot")
        cur = os.path.join(boot_attr, "current_value")

        def fake_read(path, *a, **kw):
            if os.path.abspath(path) == os.path.abspath(cur):
                raise PermissionError(cur)
            return open(path, encoding="utf-8").read().rstrip("\r\n")

        with mock.patch("uefi_policy.parsers.sysfs_dir._read_file", side_effect=fake_read):
            options = create("sysfs-dir").parse(DATA)
        boot = next(o for o in options if o.path == "hp-bioscfg/Secure Boot")
        self.assertEqual(boot.denied, ["current_value"])
        # Other fields for the same option were still read.
        self.assertEqual(boot.possible_values, ["Disable", "Enable"])


if __name__ == "__main__":
    unittest.main()
