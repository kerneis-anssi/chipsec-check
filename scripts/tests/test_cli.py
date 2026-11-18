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
            policy=self.policy_path,
            report=None,
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


class PolicyMergeDispatchTest(unittest.TestCase):
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

    def test_policy_merge_dispatch(self):
        rc = cli.main(["policy", "merge", "--review", self.review_path,
                       "--policy", self.policy_path])
        self.assertEqual(rc, 0)
        with open(self.policy_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["policy"]["hp-x/Foo"]["accept"], ["Enable"])


if __name__ == "__main__":
    unittest.main()
