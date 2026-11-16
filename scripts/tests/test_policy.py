"""Tests for policy DB and review DB load/save/merge."""

import json
import os
import tempfile
import unittest

from uefi_policy.policy import (
    DECISION_ACCEPT,
    DECISION_REJECT,
    DECISION_WILDCARD,
    Policy,
    PolicyError,
    PolicyEntry,
    ReviewEntry,
    load_policy,
    load_review,
    merge_review,
    save_policy,
    save_review,
)


class PolicyTest(unittest.TestCase):
    def test_save_load_roundtrip(self):
        p = Policy(entries={"hp-x/Foo": PolicyEntry(accept=["Enable"])})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            save_policy(p, path)
            loaded = load_policy(path)
            self.assertEqual(loaded.get("hp-x/Foo").accept, ["Enable"])

    def test_accept_and_reject_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w") as fh:
                json.dump({"version": 1, "policy": {"hp-x/Foo": {"accept": ["a"], "reject": ["b"]}}}, fh)
            with self.assertRaises(PolicyError):
                load_policy(path)


class ReviewMergeTest(unittest.TestCase):
    def _policy(self):
        return Policy(entries={"hp-x/Existing": PolicyEntry(accept=["a"])})

    def test_merge_accept(self):
        p = self._policy()
        n = merge_review(p, [ReviewEntry(path="hp-x/Existing", value="b", decision=DECISION_ACCEPT)])
        self.assertEqual(n, 1)
        self.assertEqual(p.get("hp-x/Existing").accept, ["a", "b"])

    def test_merge_bootstraps_new_option(self):
        p = self._policy()
        merge_review(p, [ReviewEntry(path="hp-x/New", value="x", decision=DECISION_ACCEPT)])
        self.assertIsNotNone(p.get("hp-x/New"))
        self.assertEqual(p.get("hp-x/New").accept, ["x"])

    def test_merge_wildcard_clears_lists(self):
        p = Policy(entries={"hp-x/W": PolicyEntry(accept=["a"])})
        merge_review(p, [ReviewEntry(path="hp-x/W", value="ignored", decision=DECISION_WILDCARD)])
        self.assertTrue(p.get("hp-x/W").wildcard)
        self.assertEqual(p.get("hp-x/W").accept, [])

    def test_merge_wildcard_all(self):
        p = self._policy()
        merge_review(p, [ReviewEntry(path="hp-x/Other", value="a", decision="review")],
                     wildcard_all=True)
        self.assertTrue(p.get("hp-x/Other").wildcard)

    def test_unresolved_raises(self):
        p = self._policy()
        with self.assertRaises(PolicyError):
            merge_review(p, [ReviewEntry(path="hp-x/Other", value="a", decision="review")])

    def test_invalid_decision_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            with open(path, "w") as fh:
                json.dump({"version": 1, "entries": [{"path": "a", "value": "b", "decision": "bogus"}]}, fh)
            with self.assertRaises(PolicyError):
                load_review(path)


if __name__ == "__main__":
    unittest.main()
