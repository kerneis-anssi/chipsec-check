"""Tests for the fwupd JSON parser."""

import json
import os
import unittest

from uefi_policy.parsers import create, detect

DATA = os.path.join(os.path.dirname(__file__), "data", "fwupd_sample.json")


def parse_sample():
    with open(DATA, encoding="utf-8") as fh:
        return create("fwupd-json").parse(fh.read())


class FwupdJsonParserTest(unittest.TestCase):
    def test_parses_expected_options(self):
        options = parse_sample()
        paths = {o.path for o in options}
        self.assertIn("hp-bioscfg/Secure Boot", paths)
        self.assertIn("hp-bioscfg/Product Name", paths)

    def test_enumeration(self):
        options = parse_sample()
        boot = next(o for o in options if o.path == "hp-bioscfg/Secure Boot")
        self.assertEqual(boot.type, "enumeration")
        self.assertEqual(boot.possible_values, ["Disable", "Enable"])
        self.assertEqual(boot.current_value, "Enable")
        self.assertEqual(boot.raw_path, "hp-bioscfg/attributes/Secure Boot")

    def test_string_no_possible_values(self):
        options = parse_sample()
        product = next(o for o in options if o.path == "hp-bioscfg/Product Name")
        self.assertEqual(product.type, "string")
        self.assertIsNone(product.possible_values)
        self.assertEqual(product.current_value, "HP EliteBook 640")

    def test_fat32_escape_canonicalized(self):
        options = parse_sample()
        gpt = next(o for o in options if o.name == "Save!Restore GPT of System Hard Drive")
        self.assertEqual(gpt.path, "hp-bioscfg/Save/Restore GPT of System Hard Drive")
        self.assertEqual(gpt.raw_path,
                         "hp-bioscfg/attributes/Save!Restore GPT of System Hard Drive")

    def test_all_options_checkable(self):
        options = parse_sample()
        self.assertTrue(all(o.is_policy_checkable for o in options))

    def test_detect_json(self):
        from uefi_policy.parsers.fwupd_json import FwupdJsonParser
        with open(DATA, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIsInstance(detect(content), FwupdJsonParser)

    def test_missing_bios_settings_raises(self):
        with self.assertRaises(ValueError):
            create("fwupd-json").parse(json.dumps({"Other": []}))


if __name__ == "__main__":
    unittest.main()
