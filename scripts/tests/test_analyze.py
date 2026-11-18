"""Tests for evaluation (analyze) and review gathering."""

import unittest

from uefi_policy.analyze import evaluate, gather_review
from uefi_policy.model import Option, Result, Status
from uefi_policy.policy import Policy, PolicyEntry
from uefi_policy.reports import build_report


def mk_option(path, cur, possible=None, otype="enumeration"):
    return Option(path=path, name=path.rsplit("/", 1)[-1], type=otype,
                  possible_values=possible, current_value=cur)


class AnalyzeTest(unittest.TestCase):
    def test_unknown_option(self):
        policy = Policy()
        r = evaluate([mk_option("hp-x/Foo", "Enable", ["Disable", "Enable"])], policy)[0]
        self.assertIn(Status.UNKNOWN_OPTION, r.statuses)

    def test_wildcard_ok(self):
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(wildcard=True)})
        r = evaluate([mk_option("hp-x/Foo", "Anything", ["Disable", "Enable"])], policy)[0]
        self.assertEqual(r.statuses, [Status.OK])

    def test_accepted_ok(self):
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable", "Disable"])})
        r = evaluate([mk_option("hp-x/Foo", "Enable", ["Disable", "Enable"])], policy)[0]
        self.assertEqual(r.statuses, [Status.OK])

    def test_rejected_violation(self):
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(reject=["Disable"])})
        r = evaluate([mk_option("hp-x/Foo", "Disable", ["Disable", "Enable"])], policy)[0]
        self.assertIn(Status.VIOLATION, r.statuses)

    def test_report_lists_violations_at_end(self):
        policy = Policy(entries={
            "hp-x/Bad": PolicyEntry(reject=["Disable"]),
            "hp-x/Good": PolicyEntry(accept=["Enable"]),
        })
        results = evaluate([
            mk_option("hp-x/Bad", "Disable", ["Disable", "Enable"]),
            mk_option("hp-x/Good", "Enable", ["Disable", "Enable"]),
        ], policy)
        report = build_report(results)
        # Violations section comes after the Summary counts.
        self.assertLess(report.index("Summary:"), report.index("Violations:"))
        self.assertIn("Bad: Disable", report)
        self.assertNotIn("hp-x/Good", report.split("Violations:")[1])

    def test_no_violations_omits_section(self):
        policy = Policy(entries={"hp-x/Good": PolicyEntry(accept=["Enable"])})
        results = evaluate([mk_option("hp-x/Good", "Enable", ["Enable"])], policy)
        self.assertNotIn("Violations:", build_report(results))

    def test_table_drops_vendor_prefix(self):
        policy = Policy(entries={"hp-x/Bad": PolicyEntry(reject=["Disable"])})
        results = evaluate([mk_option("hp-x/Bad", "Disable", ["Disable", "Enable"])],
                           policy)
        report = build_report(results)
        # Table row uses the vendor-free key, not the full path.
        body = report.split("Summary:")[0]
        self.assertIn("\nBad", body)
        self.assertNotIn("hp-x/Bad", body)

    def test_unknown_value_review(self):
        # Only "Enable" accepted; "Disable" unreviewed -> UNKNOWN_VALUE + current OK.
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable"])})
        r = evaluate([mk_option("hp-x/Foo", "Enable", ["Disable", "Enable"])], policy)[0]
        self.assertIn(Status.OK, r.statuses)
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual(review[0].path, "hp-x/Foo")
        self.assertEqual(review[0].unknown, ["Disable"])
        self.assertEqual(review[0].accept, ["Enable"])

    def test_current_unknown_and_other_unknown(self):
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable"])})
        r = evaluate([mk_option("hp-x/Foo", "Baz", ["Bar", "Enable"])], policy)[0]
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual(set(review[0].unknown), {"Baz", "Bar"})

    def test_ignored_no_type(self):
        policy = Policy()
        opt = Option(path="hp-x/Meta", name="Meta")  # no type -> metadata only
        r = evaluate([opt], policy)[0]
        self.assertIn(Status.IGNORED, r.statuses)

    def test_unset_string_not_ignored_empty_policy(self):
        # A typed string option with no current value is a real option: with an
        # empty policy it should be UNKNOWN_OPTION, not IGNORED.
        opt = Option(path="hp-x/Asset Tracking Number", name="x", type="string", current_value=None)
        r = evaluate([opt], Policy())[0]
        self.assertIn(Status.UNKNOWN_OPTION, r.statuses)
        self.assertNotIn(Status.IGNORED, r.statuses)

    def test_unset_string_covered_by_policy(self):
        # Covered but no value to compare: it surfaces for review even with no
        # enumerable value (unknown stays empty; nothing to move).
        opt = Option(path="hp-x/Asset Tracking Number", name="x", type="string", current_value=None)
        policy = Policy(entries={"hp-x/Asset Tracking Number": PolicyEntry(accept=["abc"])})
        r = evaluate([opt], policy)[0]
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual(review[0].path, "hp-x/Asset Tracking Number")
        self.assertEqual(review[0].accept, ["abc"])
        self.assertEqual(review[0].unknown, [])

    def test_unset_string_wildcard_ok(self):
        opt = Option(path="hp-x/Asset Tracking Number", name="x", type="string", current_value=None)
        policy = Policy(entries={"hp-x/Asset Tracking Number": PolicyEntry(wildcard=True)})
        r = evaluate([opt], policy)[0]
        self.assertEqual([s for s in r.statuses], [Status.OK])


if __name__ == "__main__":
    unittest.main()
