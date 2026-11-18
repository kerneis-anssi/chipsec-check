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
    load_policies,
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

    def test_accept_and_reject_both_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w") as fh:
                json.dump({"version": 1, "policy": {"hp-x/Foo": {"accept": ["a"], "reject": ["b"]}}}, fh)
            loaded = load_policy(path)
            e = loaded.get("hp-x/Foo")
            self.assertEqual(e.accept, ["a"])
            self.assertEqual(e.reject, ["b"])

    def test_accept_reject_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "policy.json")
            with open(path, "w") as fh:
                json.dump({"version": 1, "policy": {"hp-x/Foo": {"accept": ["a"], "reject": ["a"]}}}, fh)
            with self.assertRaises(PolicyError) as ctx:
                load_policy(path)
            self.assertIn("both accept and reject", str(ctx.exception))


class LoadPoliciesTest(unittest.TestCase):
    def _policy_file(self, d, name, entries):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "policy": entries}, fh)
        return path

    def test_multiple_files_merge(self):
        with tempfile.TemporaryDirectory() as d:
            a = self._policy_file(d, "a.json", {"hp-x/One": {"accept": ["x"]}})
            b = self._policy_file(d, "b.json", {"hp-x/Two": {"reject": ["y"]}})
            p = load_policies([a, b])
            self.assertEqual(set(p.entries), {"hp-x/One", "hp-x/Two"})
            self.assertEqual(p.entries["hp-x/One"].accept, ["x"])
            self.assertEqual(p.entries["hp-x/Two"].reject, ["y"])

    def test_comma_separated_and_multiple_flags(self):
        with tempfile.TemporaryDirectory() as d:
            a = self._policy_file(d, "a.json", {"hp-x/One": {"accept": ["x"]}})
            b = self._policy_file(d, "b.json", {"hp-x/Two": {"reject": ["y"]}})
            p = load_policies([f"{a},{b}"])  # comma in one spec
            self.assertEqual(set(p.entries), {"hp-x/One", "hp-x/Two"})
            # and as separate flag uses (repeatable).
            p2 = load_policies([a, b])
            self.assertEqual(set(p2.entries), {"hp-x/One", "hp-x/Two"})

    def test_directory_loads_json_non_recursive_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            self._policy_file(d, "b.json", {"hp-x/B": {"accept": ["y"]}})
            self._policy_file(d, "a.json", {"hp-x/A": {"accept": ["x"]}})
            os.mkdir(os.path.join(d, "sub"))
            self._policy_file(os.path.join(d, "sub"), "c.json", {"hp-x/C": {"reject": ["z"]}})
            self._policy_file(d, "ignore.txt", {"hp-x/X": {"accept": []}})
            p = load_policies([d])
            # non-recursive, *.json only, sorted (a before b), sub dir ignored.
            self.assertEqual(list(p.entries), ["hp-x/A", "hp-x/B"])

    def test_conflicting_key_errors(self):
        with tempfile.TemporaryDirectory() as d:
            a = self._policy_file(d, "a.json", {"hp-x/Shared": {"accept": ["x"]}})
            b = self._policy_file(d, "b.json", {"hp-x/Shared": {"reject": ["y"]}})
            with self.assertRaises(PolicyError) as ctx:
                load_policies([a, b])
            msg = str(ctx.exception)
            self.assertIn("conflicting policy key 'hp-x/Shared'", msg)
            self.assertIn("a.json", msg)
            self.assertIn("b.json", msg)


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

    def test_double_merge_roundtrip_is_idempotent(self):
        # Regression: a policy with accept+reject must reload and re-merge
        # without an exclusivity error (second merge of the same review).
        opt = ReviewOption(path="hp-x/Foo", accept=["a"], reject=["b"])
        with tempfile.TemporaryDirectory() as d:
            policies = [os.path.join(d, "policy.json") for _ in range(2)]
            for pol in policies:
                p = Policy()
                merge_review(p, [opt])
                save_policy(p, pol)
                p2 = load_policy(pol)  # must not raise
                self.assertEqual(p2.get("hp-x/Foo").accept, ["a"])
                self.assertEqual(p2.get("hp-x/Foo").reject, ["b"])

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
