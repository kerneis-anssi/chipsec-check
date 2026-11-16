# Progress

Status of the UEFI policy analyzer implementation, updated as work lands.

## Goal
Analyze UEFI configuration dumps against a JSON policy, report violations, and
support a manual review → merge workflow. See PLAN.md.

## Completed
### Step 1 — core package, model, parser, policy I/O
- `uefi_policy/` package with `model.py` (Option, Result, Status).
- `uefi_policy/parsers/` — pluggable parser registry (`base.py`), and
  `sysfs_txt.py` parsing the `grep -R .` dump into `Option` records.
  - Normalizes the always-present `/attributes/` Linux class segment out of the
    identity key (`hp-bioscfg/attributes/Secure Boot` → `hp-bioscfg/Secure Boot`).
  - Robust key discovery: splits on the rightmost `/<known-key>:` so option
    names and values containing `/` or `:` are handled (e.g. `HP_Disk0Map...`
    with PCI paths, and option names ending in `:`).
  - Reassembles multi-line values (e.g. the `authentication/SPM/status` JSON
    blob) by brace-balance detection.
- `uefi_policy/policy.py` — load/save/validate the policy DB and review DB;
  `merge_review()` applies accept/reject/wildcard, bootstraps new options, and
  enforces that unresolved `review` decisions refuse to merge.

### Step 2 — evaluation, review gathering, reporting, CLI
- `uefi_policy/analyze.py` — `evaluate()` returns per-option statuses
  (`OK`, `VIOLATION`, `UNKNOWN_OPTION`, `UNKNOWN_VALUE`, `IGNORED`), with
  options able to carry multiple statuses (e.g. VIOLATION + UNKNOWN_VALUE).
  `gather_review()` produces the review entries for unknown options/values.
- `uefi_policy/reports.py` — `build_report()` (readable table + summary).
- `uefi_policy/cli.py` + `analyze_uefi_cfg.py` — subcommands:
  - `dump <dumpfile> --policy P [--report OUT] [--review REVIEW]`
  - `merge --review R --policy P [--wildcard-all] [--backup]`
  - A missing policy is treated as empty during merge (allows building a DB
    from scratch via review).

### Step 3 — tests & docs
- Unit tests: `tests/test_parsers.py`, `tests/test_analyze.py`,
  `tests/test_policy.py`, plus a small fixture `tests/data/sample.txt`.
- `README.md` with usage and file-format documentation.

## Remaining / possible follow-ups
- A separate review-only helper (plan mentions possible "separate script") —
  the review file already doubles as the manual artifact.
- Optionally expose the raw source path in reports for sysfs correlation
  (`Option.raw_path` is already stored).
- Per-value glob/regex matching (explicitly out of scope for v1; schema can be
  extended later).
