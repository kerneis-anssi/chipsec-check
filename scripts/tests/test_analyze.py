"""Tests for evaluation (analyze) and review gathering."""

import unittest

from uefi_policy.analyze import evaluate, gather_review
from uefi_policy.model import Option, Result, Status
from uefi_policy.policy import Policy, PolicyEntry


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

    def test_unknown_value_review(self):
        # Only "Enable" accepted; "Disable" unreviewed -> UNKNOWN_VALUE + current OK.
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable"])})
        r = evaluate([mk_option("hp-x/Foo", "Enable", ["Disable", "Enable"])], policy)[0]
        self.assertIn(Status.OK, r.statuses)
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual([e.value for e in review], ["Disable"])

    def test_current_unknown_and_other_unknown(self):
        policy = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable"])})
        r = evaluate([mk_option("hp-x/Foo", "Baz", ["Bar", "Enable"])], policy)[0]
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual({e.value for e in review}, {"Baz", "Bar"} | set())

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
        # Covered but no value to compare: flags for review (not ignored), and
        # still surfaces as a review entry even with no enumerable value.
        opt = Option(path="hp-x/Asset Tracking Number", name="x", type="string", current_value=None)
        policy = Policy(entries={"hp-x/Asset Tracking Number": PolicyEntry(accept=["abc"])})
        r = evaluate([opt], policy)[0]
        self.assertIn(Status.UNKNOWN_VALUE, r.statuses)
        review = gather_review([r], policy)
        self.assertEqual([(e.path, e.value) for e in review],
                         [("hp-x/Asset Tracking Number", "")])

    def test_unset_string_wildcard_ok(self):
        opt = Option(path="hp-x/Asset Tracking Number", name="x", type="string", current_value=None)
        policy = Policy(entries={"hp-x/Asset Tracking Number": PolicyEntry(wildcard=True)})
        r = evaluate([opt], policy)[0]
        self.assertEqual([s for s in r.statuses], [Status.OK])


if __name__ == "__main__":
    unittest.main()
