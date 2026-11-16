"""Command-line interface: ``dump`` (analyze) and ``merge``."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from uefi_policy.analyze import evaluate, gather_review
from uefi_policy.parsers import available, create
from uefi_policy.policy import Policy, PolicyError, load_policy, load_review, merge_review, save_policy, save_review
from uefi_policy.reports import build_report, write_report


def _read_source(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def cmd_dump(args: argparse.Namespace, stream=None) -> int:
    stream = stream or sys.stdout
    source = _read_source(args.input)
    parser = create(args.format)
    options = parser.parse(source)

    policy = load_policy(args.policy)
    results = evaluate(options, policy)
    report = build_report(results)
    write_report(report, stream)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"report written to {args.report}")

    review = gather_review(results, policy)
    if review:
        review_path = args.review
        if review_path == "auto" or review_path is None:
            review_path = args.input + ".review.json"
        save_review(review, review_path)
        print(f"review file ({len(review)} entries) written to {review_path}")
    elif args.review and args.review != "auto":
        print(f"no unknown options/values; no review file written ({args.review})")

    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    try:
        policy = load_policy(args.policy) if os.path.exists(args.policy) else Policy()
        entries = load_review(args.review)
        applied = merge_review(policy, entries, wildcard_all=args.wildcard_all)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    save_policy(policy, args.policy, backup=args.backup)
    print(f"merged {applied} entries into {args.policy}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analyze_uefi_cfg.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=False)

    dump = sub.add_parser("dump", help="analyze a configuration dump against a policy")
    dump.add_argument("input", help="path to the configuration dump text file")
    dump.add_argument("--format", default="sysfs-txt", choices=available(),
                      help="input parser (default: sysfs-txt)")
    dump.add_argument("--policy", required=True, help="policy JSON database")
    dump.add_argument("--report", metavar="OUT", help="also write the report to this text file")
    dump.add_argument("--review", nargs="?", const="auto", default=None,
                      help="write review file here (default: <input>.review.json)")
    dump.set_defaults(func=cmd_dump)

    merge = sub.add_parser("merge", help="merge a reviewed file into the policy")
    merge.add_argument("--review", metavar="REVIEW", required=True, help="review JSON file")
    merge.add_argument("--policy", required=True, help="policy JSON database (updated in place)")
    merge.add_argument("--wildcard-all", action="store_true",
                       help="treat every 'review' decision as a wildcard")
    merge.add_argument("--backup", action="store_true", help="keep a .bak copy of the policy")
    merge.set_defaults(func=cmd_merge)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)
