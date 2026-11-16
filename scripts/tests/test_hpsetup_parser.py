"""Tests for the HP Setup text parser."""

import os
import unittest

from uefi_policy.parsers import create

DATA = os.path.join(os.path.dirname(__file__), "data", "hpsetup_sample.txt")


def parse_sample():
    with open(DATA, "rb") as fh:
        raw = fh.read()
    # Fixture is CRLF text (utf-8); decode directly.
    return create("hp-setup").parse(raw.decode("utf-8"))


class HPSetupTxtParserTest(unittest.TestCase):
    def test_enumeration_star_marked_current(self):
        options = parse_sample()
        boot = next(o for o in options if o.name == "Secure Boot")
        self.assertEqual(boot.type, "enumeration")
        self.assertEqual(boot.possible_values, ["Disable", "Enable"])
        self.assertEqual(boot.current_value, "Enable")
        self.assertEqual(boot.path, "hp-bioscfg/Secure Boot")

    def test_scalar_single_value(self):
        options = parse_sample()
        product = next(o for o in options if o.name == "Product Name")
        self.assertEqual(product.type, "string")
        self.assertEqual(product.current_value, "HP EliteBook 640")
        self.assertIsNone(product.possible_values)

    def test_ordered_list(self):
        options = parse_sample()
        boot_order = next(o for o in options if o.name == "UEFI Boot Order")
        self.assertEqual(boot_order.type, "ordered-list")
        self.assertEqual(boot_order.possible_values, ["HDD:M.2:1", "HDD:USB:1"])
        self.assertEqual(boot_order.current_value, "HDD:M.2:1;HDD:USB:1")


if __name__ == "__main__":
    unittest.main()
