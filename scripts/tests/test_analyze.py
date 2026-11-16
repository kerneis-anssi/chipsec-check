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
        opt = Option(path="hp-x/Meta", name="Meta")  # no type/current_value
        r = Result(opt)
        r.statuses.append(Status.IGNORED)
        self.assertEqual(r.primary_status, Status.IGNORED)


if __name__ == "__main__":
    unittest.main()
