"""Tests for the command-line interface."""
import io
import json
import os
import shutil
import tempfile
import unittest
from argparse import Namespace

from uefi_policy import cli

DATA = os.path.join(os.path.dirname(__file__), "data")


class CheckReviewOverwriteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp)
        self.input_path = os.path.join(self._tmp, "dump.json")
        self.policy_path = os.path.join(self._tmp, "policy.json")
        self.review_path = os.path.join(self._tmp, "review.json")
        shutil.copy(os.path.join(DATA, "fwupd_sample.json"), self.input_path)
        with open(self.policy_path, "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "policy": {}}\n')

    def args(self, review=None, **kw):
        base = dict(
            input=self.input_path,
            format="auto",
            policy=[self.policy_path],
            review=review,
        )
        base.update(kw)
        return Namespace(**base)

    def test_refuses_to_overwrite_existing_review(self):
        sentinel = "# previous review, do not clobber\n"
        with open(self.review_path, "w", encoding="utf-8") as fh:
            fh.write(sentinel)

        rc = cli.cmd_check(self.args(review=self.review_path), stream=io.StringIO())

        self.assertEqual(rc, 1)
        with open(self.review_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), sentinel)

    def test_refuses_to_overwrite_auto_named_review(self):
        auto_path = self.input_path + ".review.json"
        sentinel = "# previous review\n"
        with open(auto_path, "w", encoding="utf-8") as fh:
            fh.write(sentinel)

        rc = cli.cmd_check(self.args(review=None), stream=io.StringIO())

        self.assertEqual(rc, 1)
        with open(auto_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), sentinel)

    def test_writes_review_when_file_is_new(self):
        rc = cli.cmd_check(self.args(review=self.review_path), stream=io.StringIO())
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.review_path))


class PolicyUpdateDispatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp)
        self.policy_path = os.path.join(self._tmp, "policy.json")
        self.review_path = os.path.join(self._tmp, "review.json")
        with open(self.policy_path, "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "policy": {}}\n')
        review = {
            "version": 2,
            "review": {
                "hp-x/Foo": {"accept": ["Enable"], "reject": [],
                             "current": "Enable", "unknown": []},
            },
        }
        with open(self.review_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(review) + "\n")

    def test_policy_update_dispatch(self):
        rc = cli.main(["policy", "update", "--review", self.review_path,
                       "--policy", self.policy_path])
        self.assertEqual(rc, 0)
        with open(self.policy_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["policy"]["hp-x/Foo"]["accept"], ["Enable"])


class PolicyShowTest(unittest.TestCase):
    @staticmethod
    def _policy(**kw):
        from uefi_policy.policy import Policy, PolicyEntry
        p = Policy()
        for key, entry in kw.items():
            p.entries[key] = PolicyEntry(**entry)
        return p

    def _sample(self):
        return self._policy(
            **{
                "hp-x/Audio": {"reject": ["Muted"]},
                "hp-x/Secure Boot": {"accept": ["Enable"], "reject": ["Disable"]},
                "hp-x/Bluetooth": {"wildcard": True},
                "hp-x/TPM": {"wildcard": True},
            }
        )

    def test_last_groups_wildcards_at_end(self):
        from uefi_policy.reports import format_policy
        text = format_policy(self._sample(), "last")
        audio = text.index("hp-x/Audio:")
        secure = text.index("hp-x/Secure Boot:")
        bt = text.index("hp-x/Bluetooth:")
        tpm = text.index("hp-x/TPM:")
        self.assertLess(audio, secure)  # normal entries sorted by key
        self.assertLess(audio, bt)      # wildcards grouped after normal
        self.assertLess(bt, tpm)        # wildcards sorted among themselves
        self.assertIn("accept: Enable", text)
        self.assertIn("reject: Disable", text)
        self.assertIn("wildcard: true", text)

    def test_inline_keeps_all_sorted_together(self):
        from uefi_policy.reports import format_policy
        text = format_policy(self._sample(), "inline")
        keys = ["hp-x/Audio:", "hp-x/Bluetooth:", "hp-x/Secure Boot:", "hp-x/TPM:"]
        positions = [text.index(k) for k in keys]
        self.assertEqual(positions, sorted(positions))

    def test_no_omits_wildcards(self):
        from uefi_policy.reports import format_policy
        text = format_policy(self._sample(), "no")
        self.assertNotIn("Bluetooth", text)
        self.assertNotIn("TPM", text)
        self.assertIn("hp-x/Secure Boot:", text)

    def test_show_dispatch(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False) as fh:
            json.dump({"version": 1, "policy": {
                "hp-x/Secure Boot": {"accept": ["Enable"], "reject": ["Disable"]},
            }}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        out = io.StringIO()
        rc = cli.cmd_show(
            Namespace(policy=[path], show_wildcards="no", json=None), stream=out)
        self.assertEqual(rc, 0)
        self.assertIn("hp-x/Secure Boot:", out.getvalue())

    def test_show_json_writes_ordered_policy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = os.path.join(tmp, "policy.json")
            with open(policy_path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "policy": {
                    "hp-x/Audio": {"reject": ["Muted"]},
                    "hp-x/Secure Boot": {"accept": ["Enable"], "reject": ["Disable"]},
                    "hp-x/Bluetooth": {"wildcard": True},
                    "hp-x/TPM": {"wildcard": True},
                }}, fh)
            out_path = os.path.join(tmp, "out.json")
            out = io.StringIO()
            rc = cli.cmd_show(
                Namespace(policy=[policy_path], show_wildcards="last", json=out_path),
                stream=out,
            )
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["version"], 1)
            keys = list(data["policy"].keys())
            self.assertEqual(keys, ["hp-x/Audio", "hp-x/Secure Boot",
                                    "hp-x/Bluetooth", "hp-x/TPM"])
            # Values carried over from the policy.
            self.assertEqual(data["policy"]["hp-x/Secure Boot"]["accept"],
                             ["Enable"])
            self.assertTrue(data["policy"]["hp-x/Bluetooth"]["wildcard"])

    def test_show_json_no_omits_wildcards(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = os.path.join(tmp, "policy.json")
            with open(policy_path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "policy": {
                    "hp-x/Secure Boot": {"accept": ["Enable"]},
                    "hp-x/TPM": {"wildcard": True},
                }}, fh)
            out_path = os.path.join(tmp, "out.json")
            rc = cli.cmd_show(
                Namespace(policy=[policy_path], show_wildcards="no", json=out_path),
                stream=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            with open(out_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(list(data["policy"].keys()), ["hp-x/Secure Boot"])


class WildcardAllPreservesDecisionsTest(unittest.TestCase):
    """check --review then policy update --wildcard-all (unedited) must not
    lose existing accept/reject decisions -- only undecided options become
    wildcards."""

    DUMP = {
        "BiosSettings": [
            {
                "Name": "Audio",
                "Filename": "/sys/class/firmware-attributes/hp-x/attributes/Audio",
                "BiosSettingCurrentValue": "On",
                "BiosSettingType": 1,
                "BiosSettingPossibleValues": ["On", "Muted", "Off"],
            },
            {
                "Name": "Network",
                "Filename": "/sys/class/firmware-attributes/hp-x/attributes/Network",
                "BiosSettingCurrentValue": "On",
                "BiosSettingType": 1,
                "BiosSettingPossibleValues": ["On", "Off"],
            },
        ]
    }

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp)
        self.dump_path = os.path.join(self._tmp, "dump.json")
        self.policy_path = os.path.join(self._tmp, "policy.json")
        self.review_path = os.path.join(self._tmp, "review.json")
        with open(self.dump_path, "w", encoding="utf-8") as fh:
            json.dump(self.DUMP, fh)
        # Audio already has accept/reject; "Off" is unknown so it needs review.
        with open(self.policy_path, "w", encoding="utf-8") as fh:
            json.dump({
                "version": 1,
                "policy": {
                    "hp-x/Audio": {"accept": ["On"], "reject": ["Muted"]},
                },
            }, fh)

    def test_wildcard_all_preserves_accept_reject(self):
        # Step 1: check produces a review carrying the existing accept/reject.
        rc = cli.cmd_check(Namespace(input=self.dump_path, format="auto",
                                     policy=[self.policy_path],
                                     review=self.review_path),
                           stream=io.StringIO())
        self.assertEqual(rc, 0)
        with open(self.review_path, encoding="utf-8") as fh:
            review = json.load(fh)
        self.assertEqual(review["review"]["hp-x/Audio"]["accept"], ["On"])
        self.assertEqual(review["review"]["hp-x/Audio"]["reject"], ["Muted"])

        # Step 2: update --wildcard-all without editing the review.
        rc = cli.cmd_update(Namespace(review=self.review_path,
                                      policy=self.policy_path,
                                      wildcard_all=True, backup=False))
        self.assertEqual(rc, 0)

        # Audio's existing accept/reject are preserved (not turned into a
        # wildcard), even though its unknown "Off" value triggered review.
        with open(self.policy_path, encoding="utf-8") as fh:
            policy = json.load(fh)
        self.assertEqual(policy["policy"]["hp-x/Audio"]["accept"], ["On"])
        self.assertEqual(policy["policy"]["hp-x/Audio"]["reject"], ["Muted"])
        self.assertNotIn("wildcard", policy["policy"]["hp-x/Audio"])
        # The undecided option not in the policy became a wildcard.
        self.assertTrue(policy["policy"]["hp-x/Network"]["wildcard"])


if __name__ == "__main__":
    unittest.main()
