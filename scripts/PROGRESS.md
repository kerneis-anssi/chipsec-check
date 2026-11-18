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
- `uefi_policy/cli.py` + `fwsetup` — subcommands:
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

### Step 7 — don't ignore unset (typed) options
- `IGNORED` is now reserved for pure metadata rows only: `Option.is_policy_checkable`
  returns `type is not None`. A typed option (e.g. a `string`) with no
  `current_value` in the dump is never silently ignored.
  - Empty policy → `UNKNOWN_OPTION`.
  - Policy-covered → `UNKNOWN_VALUE` (nothing to compare) unless wildcarded → `OK`.
- `gather_review` surfaces a covered-but-unset option as a review entry with an
  empty value, so it is not silently dropped from the review workflow.
- Result on the real dump: `IGNORED` dropped from 25 → 1 (only `Sure_Start`, a
  type-less row). The 23 unset strings now report instead of being ignored.

### Step 8 — fwupd JSON parser (structured replacement for the grep dump)
- Added `uefi_policy/parsers/fwupd_json.py` (`FwupdJsonParser`, format
  `fwupd-json`) for fwupd `get-bios-settings` output — the same content as the
  sysfs dump but structured as `{"BiosSettings": [...]}`.
  - Only two types: an option with a `BiosSettingPossibleValues` list is
    `enumeration`; everything else is `string`.
  - Derives the canonical policy key from each entry's `Filename` sysfs path
    (strip the prefix and `/attributes/`, undo `!` → `/`).
  - `BiosSettingCurrentValue` → `current_value`; other fields (description,
    read-only, bounds, ids) kept in `metadata`.
- Auto-detection: a JSON object starting with `{` selects the fwupd parser.
- Tests: `tests/test_fwupd_parser.py` + `tests/data/fwupd_sample.json`.
- End-to-end: 262 options, all checkable (162 enumeration + 100 string).

### Step 9 — discard the grep-based sysfs-txt format
- Removed `uefi_policy/parsers/sysfs_txt.py`, its tests
  (`tests/test_parsers.py`) and fixture (`tests/data/sample.txt`); dropped the
  `sysfs-txt` registration and the grep line-splitting logic.
- Auto-detection now simple: JSON starting with `{` → `fwupd-json`, otherwise
  `hp-setup`.
- Docs (README/PLAN) rewritten to treat fwupd JSON as the primary input. The
  `fwupd-json` and `hp-setup` formats remain.

### Step 10 — sysfs firmware-attributes directory parser
- Added `uefi_policy/parsers/sysfs_dir.py` (`SysfsDirParser`, format
  `sysfs-dir`). Given a directory (assumed to be `/sys/class/firmware-attributes`
  or a copy), it descends `<vendor>/attributes/*` and reads each option's
  attribute files.
  - Only the `attributes` class is parsed; `authentication`/`power` and
    module-level scalars like `pending_reboot` are skipped (matching fwupd).
  - Mirrors the fwupd typing: an option with a `possible_values`/`elements`
    file is `enumeration`, otherwise `string` — so the two structured sources
    reconcile to identical policy keys.
  - Canonical key built from the on-disk `<vendor>/attributes/<option>` path
    (strip `attributes`, undo `!` → `/`).
- CLI: `dump` accepts a directory; with `--format auto` or `sysfs-dir` it uses
  this parser. A directory passed with a non-directory format raises a clear
  error.
- Tests: `tests/test_sysfs_dir_parser.py` + `tests/data/sysfs_dir/` fixture.

### Step 11 — per-option review format (mirror the policy file)
- Replaced the per-value `(path, value, decision)` review entries with a
  per-option format that mirrors the policy file: the review file now has a
  `review` object keyed by option path, where each value is an option dict with
  `accept`/`reject`/`wildcard` plus `current` (observed value) and `unknown`
  (undecided values). A reviewer just moves values between `accept`/`reject` or
  sets `wildcard: true`.
- `gather_review()` returns `List[ReviewOption]`; `merge_review()` now takes
  `ReviewOption`s and returns `(applied, skipped)`. Merged lists **replace** the
  policy entry (the review file is authoritative), and an option left fully
  undecided is **skipped silently** (counted in `skipped`) unless `--wildcard-all`
  promotes it to a wildcard.
- Removed the obsolete `DECISION_*`/`VALID_DECISIONS` constants and `ReviewEntry`.
  `REVIEW_VERSION` bumped 1 → 2 (policy version stays 1).
- Tests: `test_policy.py` rewritten for `ReviewOption` (accept/bootstrap/
  wildcard/wildcard-all/undecided-skipped/reject/conflict/I-O roundtrip/invalid/
  missing `review` object); `test_analyze.py` assertions updated for the
  per-option `unknown` lists. 42 tests pass.

### Step 13 — check refuses to overwrite an existing review file
- `cmd_check` now refuses to write a review file if its target already exists
  (both an explicit `--review PATH` and the auto-named `<input>.review.json`),
  returning a non-zero exit instead of clobbering a prior, possibly-edited
  review. This protects against accidentally re-running `check` instead of
  `policy merge` and losing review work.
- Tests: `tests/test_cli.py` — overwrite refusal for explicit and auto-named
  review paths (target file left untouched), and the happy-path write for a new
  file. 48 tests pass.

### Step 14 — reorganize the CLI verbs
- Renamed the analyze verb `dump` → `check` (`fwsetup check`).
- Moved `merge` under a new **`policy`** subcommand: `fwsetup
  policy merge …`. The `policy` subcommand is deliberately structured to host
  future `policy show` and `policy review` verbs later.
- Updated the CLI parser, handlers, tests (incl. a new `policy merge` dispatch
  test) and the README/PLAN usage docs.

### Step 15 — policy show
- Added `fwsetup policy show --policy P [--show-wildcards …]`, a
  pretty-printed terminal view of the policy: each key shows its `accept` and
  `reject` values (or `wildcard: true`).
- `--show-wildcards` (default `last`) controls wildcard-only entries: `last`
  groups them at the end sorted by key among themselves; `inline` keeps them
  sorted with all keys; `no` omits them.
- `format_policy()` in `reports.py`; `cmd_show` wired into the `policy`
  subcommand. Tests in `tests/test_cli.py` cover the three modes, ordering, and
  CLI dispatch. Docs updated in README/PLAN.

### Step 17 — policy show --json
- Added `--json OUT` to `fwsetup policy show`: it writes the policy itself as a
  JSON file (version 1 format), with options ordered per `--show-wildcards` (so
  `no` omits wildcard-only entries).
- Refactored `reports.py` to expose `ordered_entries()`, shared by `format_policy`
  and the JSON output. Tests cover write-on-show, ordering, and the
  `no` mode omission. Docs updated in README/PLAN.

### Step 16 — rename the CLI tool to fwsetup
- Renamed the entry-point script `analyze_uefi_cfg.py` → `fwsetup`, and the
  `argparse` `prog` is now `fwsetup`. Updated all command invocations in the
  README/PLAN/PROGRESS docs accordingly.

### Step 12 — allow accept+reject together in one option
- Decided to flag `UNKNOWN_VALUE` for the full enumerable `possible_values` set
  (not just the current value), so every newly-possible enum value must be
  explicitly mapped. This means a fully-decided enumeration legitimately needs
  **both** `accept` and `reject` filled.
- `merge_review` no longer treats `accept`/`reject` as mutually exclusive: it
  stores both lists for an option. A value appearing in both lists is still
  rejected as malformed (overlap).
- Review files already emit both lists (see Step 11 formatting); reviewers now
  move each unknown value into `accept` or `reject` to converge an option.
- Tests: replaced the exclusivity test with `accept`+`reject` merge and an
  overlap-raises test; 43 tests pass.

## Known caveats / notes
- Cross-format name reconciliation: HP exposes `/` in option names as `!`,
  because `/` is forbidden in filenames (FAT32). Both the fwupd JSON `Name`/
  `Filename` and the HP Setup report carry the same option, and the parsers
  canonicalize `!` → `/`, so both sources produce identical policy keys
  (e.g. `hp-bioscfg/Save/Restore GPT of System Hard Drive`). The HP Setup
  report already uses `/`, so the two formats fully reconcile.

## Remaining / possible follow-ups
- A separate review-only helper (plan mentions possible "separate script") —
  the review file already doubles as the manual artifact.
- Optionally expose the raw source path in reports for sysfs correlation
  (`Option.raw_path` is already stored).
- Per-value glob/regex matching (explicitly out of scope for v1; schema can be
  extended later).
