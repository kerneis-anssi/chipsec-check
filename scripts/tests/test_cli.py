"""Tests for the command-line interface."""
import io
import os
import shutil
import tempfile
import unittest
from argparse import Namespace

from uefi_policy import cli

DATA = os.path.join(os.path.dirname(__file__), "data")


class DumpReviewOverwriteTest(unittest.TestCase):
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

        rc = cli.cmd_dump(self.args(review=self.review_path), stream=io.StringIO())

        self.assertEqual(rc, 1)
        with open(self.review_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), sentinel)

    def test_refuses_to_overwrite_auto_named_review(self):
        auto_path = self.input_path + ".review.json"
        sentinel = "# previous review\n"
        with open(auto_path, "w", encoding="utf-8") as fh:
            fh.write(sentinel)

        rc = cli.cmd_dump(self.args(review=None), stream=io.StringIO())

        self.assertEqual(rc, 1)
        with open(auto_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), sentinel)

    def test_writes_review_when_file_is_new(self):
        rc = cli.cmd_dump(self.args(review=self.review_path), stream=io.StringIO())
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.review_path))


if __name__ == "__main__":
    unittest.main()
