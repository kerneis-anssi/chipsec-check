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

### Step 4 — HP Setup text format parser
- Added `uefi_policy/parsers/hpsetup_txt.py` (`HPSetupTxtParser`, format
  name `hp-setup`) for HP `HPSetup.txt`-style host reports.
  - Format: option name lines followed by tab-indented value lines.
  - `*`-prefixed value in a selectable option ⇒ enumeration (all listed values
    are `possible_values`, the `*` one is `current_value`).
  - Single value line, no `*` ⇒ scalar `string`/`integer` current value.
  - Multiple value lines, no `*` ⇒ `ordered-list`: values are the
    `possible_values`/elements and `current_value` is their `;`-joined form
    (mirrors the sysfs dump, where an ordered-list current_value equals its
    elements joined by `;`).
  - No vendor prefix in this format ⇒ options namespaced under `hp-bioscfg/`
    to share policy keys with the sysfs-derived model.
- Format auto-detection (`--format auto`, the default): sniffs sysfs
  (`/`-path + `:` lines) vs HP Setup (bare names) from the first non-empty /
  non-indented line.
- UTF-16 input support: `cli._read_source()` detects a UTF-16 BOM and decodes
  accordingly (the HpSetup.txt fixture is UTF-16/CRLF).
- Cross-format name reconciliation: the sysfs parser canonicalizes HP's `!`
  FAT32-safe escape back to `/` in option names, producing identical policy
  keys between the sysfs dump and the HP Setup report.
- Tests: `tests/test_hpsetup_parser.py` + `tests/data/hpsetup_sample.txt`.

### Step 5 — focusing the sysfs parser on `/attributes/` + single-line guard
- The sysfs parser now keeps **only real options** under the
  `<vendor>/attributes/` class. HP-specific non-option data under `authentication/`
  and `power/`, and module-level scalars like `pending_reboot:0`, are discarded.
- Dropped the authentication/power-specific field keys from the known-key list.
- Real `/attributes/` values are single-line (no multi-line values exist in
  practice), so multi-line assembly was removed entirely. A repeated `(path, key)`
  now raises a `ValueError` instead of being joined or silently overwritten.
- Tests updated: non-`attributes` classes are asserted discarded, the
  class-level scalar is discarded, and a duplicate key raises.

### Step 6 — harden JSON loading (empty/malformed files)
- `load_policy`/`load_review` now route parsing through `_load_json()`, which
  turns empty files, invalid JSON, decode and I/O errors into a clear
  `PolicyError` instead of an uncaught traceback.
- CLI: `cmd_dump` catches `PolicyError`/`ValueError`; `main` catches a stray
  `PolicyError` and `BrokenPipeError`, printing a clean error + non-zero exit.
- Tests: empty/malformed/non-object policy files, plus existing coverage.

## Known caveats / notes
- Cross-format name reconciliation: HP exposes `/` in option names as `!` in
  the sysfs dump (FAT32 forbids `/` in filenames). The sysfs parser now
  canonicalizes `!` → `/`, so both sources produce identical policy keys
  (e.g. `hp-bioscfg/Save/Restore GPT of System Hard Drive`). The HP Setup
  report already uses `/`, so the two formats fully reconcile.

## Remaining / possible follow-ups
- A separate review-only helper (plan mentions possible "separate script") —
  the review file already doubles as the manual artifact.
- Optionally expose the raw source path in reports for sysfs correlation
  (`Option.raw_path` is already stored).
- Per-value glob/regex matching (explicitly out of scope for v1; schema can be
  extended later).
