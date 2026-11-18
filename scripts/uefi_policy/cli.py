"""Command-line interface: ``check`` (analyze) and ``policy`` (merge; later show/review)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from uefi_policy.analyze import evaluate, gather_review
from uefi_policy.parsers import available, create, detect
from uefi_policy.policy import Policy, PolicyError, load_policy, load_review, merge_review, save_policy, save_review
from uefi_policy.reports import build_report, write_report


def _read_source(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def cmd_check(args: argparse.Namespace, stream=None) -> int:
    stream = stream or sys.stdout
    try:
        if os.path.isdir(args.input):
            # A directory: assume /sys/class/firmware-attributes (or a copy).
            if args.format not in ("auto", "sysfs-dir"):
                raise ValueError(
                    f"input {args.input!r} is a directory, expected --format auto "
                    "or sysfs-dir"
                )
            parser = create("sysfs-dir")
            options = parser.parse(args.input)
        else:
            source = _read_source(args.input)
            if args.format == "auto":
                parser = detect(source)
            else:
                parser = create(args.format)
            options = parser.parse(source)
        policy = load_policy(args.policy)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

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
        # Refuse to clobber an existing review file: re-running "check" (instead
        # of "policy merge") must not lose a prior, possibly-edited review.
        if os.path.exists(review_path):
            print(
                f"error: review file {review_path} already exists; refusing to "
                "overwrite it. Merge (or move) it first, or pick a new --review path.",
                file=sys.stderr,
            )
            return 1
        save_review(review, review_path)
        print(f"review file ({len(review)} entries) written to {review_path}")
    elif args.review and args.review != "auto":
        print(f"no unknown options/values; no review file written ({args.review})")

    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    try:
        policy = load_policy(args.policy) if os.path.exists(args.policy) else Policy()
        entries = load_review(args.review)
        applied, skipped = merge_review(policy, entries, wildcard_all=args.wildcard_all)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    save_policy(policy, args.policy, backup=args.backup)
    msg = f"merged {applied} entries into {args.policy}"
    if skipped:
        msg += f" (skipped {skipped} undecided)"
    print(msg)
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analyze_uefi_cfg.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=False)

    check = sub.add_parser("check", help="analyze a configuration dump against a policy")
    check.add_argument("input", help="path to a config dump file or a sysfs firmware-attributes directory")
    check.add_argument("--format", default="auto", choices=["auto"] + available(),
                       help="input parser (default: auto-detect)")
    check.add_argument("--policy", required=True, help="policy JSON database")
    check.add_argument("--report", metavar="OUT", help="also write the report to this text file")
    check.add_argument("--review", nargs="?", const="auto", default=None,
                       help="write review file here (default: <input>.review.json)")
    check.set_defaults(func=cmd_check)

    # "policy" will later host "show", "review", ... alongside "merge".
    policy = sub.add_parser("policy", help="manage the policy database")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    merge = policy_sub.add_parser("merge", help="merge a reviewed file into the policy")
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
    try:
        return args.func(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
