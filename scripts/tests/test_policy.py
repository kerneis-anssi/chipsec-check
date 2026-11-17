"""Tests for policy DB and review DB load/save/merge."""

import json
import os
import tempfile
import unittest

from uefi_policy.policy import (
    Policy,
    PolicyError,
    PolicyEntry,
    ReviewOption,
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

    def test_empty_policy_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w", encoding="utf-8"):  # 0-byte file
                pass
            with self.assertRaises(PolicyError) as ctx:
                load_policy(path)
            self.assertIn("empty", str(ctx.exception))

    def test_malformed_policy_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with self.assertRaises(PolicyError) as ctx:
                load_policy(path)
            self.assertIn("invalid JSON", str(ctx.exception))

    def test_non_object_policy_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(["not", "an", "object"]))
            with self.assertRaises(PolicyError):
                load_policy(path)

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
        applied, skipped = merge_review(
            p, [ReviewOption(path="hp-x/Existing", accept=["a", "b"])])
        self.assertEqual((applied, skipped), (1, 0))
        self.assertEqual(p.get("hp-x/Existing").accept, ["a", "b"])

    def test_merge_bootstraps_new_option(self):
        p = self._policy()
        merge_review(p, [ReviewOption(path="hp-x/New", accept=["x"])])
        self.assertIsNotNone(p.get("hp-x/New"))
        self.assertEqual(p.get("hp-x/New").accept, ["x"])

    def test_merge_wildcard_clears_lists(self):
        p = Policy(entries={"hp-x/W": PolicyEntry(accept=["a"])})
        merge_review(p, [ReviewOption(path="hp-x/W", wildcard=True)])
        self.assertTrue(p.get("hp-x/W").wildcard)
        self.assertEqual(p.get("hp-x/W").accept, [])

    def test_merge_wildcard_all(self):
        p = self._policy()
        # An undecided option becomes a wildcard under --wildcard-all.
        applied, _ = merge_review(
            p, [ReviewOption(path="hp-x/Other", unknown=["a"])], wildcard_all=True)
        self.assertEqual(applied, 1)
        self.assertTrue(p.get("hp-x/Other").wildcard)

    def test_undecided_skipped(self):
        p = self._policy()
        applied, skipped = merge_review(
            p, [ReviewOption(path="hp-x/Other", unknown=["a"])])
        self.assertEqual((applied, skipped), (0, 1))
        self.assertIsNone(p.get("hp-x/Other"))

    def test_merge_reject(self):
        p = Policy()
        merge_review(p, [ReviewOption(path="hp-x/Foo", reject=["Disable"])])
        self.assertEqual(p.get("hp-x/Foo").reject, ["Disable"])

    def test_merge_accept_and_reject(self):
        p = Policy()
        merge_review(
            p, [ReviewOption(path="hp-x/Foo", accept=["a"], reject=["b"])])
        e = p.get("hp-x/Foo")
        self.assertEqual(e.accept, ["a"])
        self.assertEqual(e.reject, ["b"])
        self.assertFalse(e.wildcard)

    def test_merge_accept_reject_overlap_raises(self):
        p = Policy()
        with self.assertRaises(PolicyError):
            merge_review(
                p, [ReviewOption(path="hp-x/Foo", accept=["a"], reject=["a"])])

    def test_review_io_roundtrip(self):
        opt = ReviewOption(path="hp-x/Foo", accept=["Enable"], current="Disable",
                           unknown=["Disable"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            save_review([opt], path)
            loaded = load_review(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].accept, ["Enable"])
            self.assertEqual(loaded[0].current, "Disable")
            self.assertEqual(loaded[0].unknown, ["Disable"])
            # accept/reject always emitted (even empty), on their own lines.
            raw = open(path, encoding="utf-8").read()
            self.assertIn('"reject": [', raw)
            self.assertIn('"accept": [', raw)

    def test_invalid_review_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            with open(path, "w") as fh:
                json.dump({"version": 2, "review": {"a": {"accept": "not-a-list"}}}, fh)
            with self.assertRaises(PolicyError):
                load_review(path)

    def test_missing_review_object_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "review.json")
            with open(path, "w") as fh:
                json.dump({"version": 2, "entries": []}, fh)
            with self.assertRaises(PolicyError) as ctx:
                load_review(path)
            self.assertIn("review", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
