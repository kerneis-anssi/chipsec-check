# UEFI Configuration Policy Analyzer — Design Plan

A Python tool that parses UEFI configuration dumps, evaluates them against a
policy database, reports violations, and supports a review/merge workflow for
options and values not yet covered by the policy.

## 1. Input data format (fwupd JSON)

The primary input is structured JSON produced by fwupd's
`fwupdmgr get-bios-settings`. It contains the same options as the legacy
grep dump but in a clean, structured form:

```
{
  "BiosSettings": [
    {
      "Name": "Secure Boot",
      "Filename": "/sys/class/firmware-attributes/hp-bioscfg/attributes/Secure Boot",
      "BiosSettingCurrentValue": "Enable",
      "BiosSettingType": 1,
      "BiosSettingPossibleValues": ["Disable", "Enable"],
      ...
    },
    ...
  ]
}
```

### Parsing rules / gotchas

- **Option identity**: each entry's `Filename` mirrors the sysfs path
  (`.../firmware-attributes/<vendor>/<class>/<option>`). We derive the policy
  key by stripping the sysfs prefix and the always-present `/attributes/`
  class segment, then undoing HP's FAT32-safe `!` → `/` escape
  (e.g. → `hp-bioscfg/Secure Boot`, `hp-bioscfg/Save/Restore GPT of ...`).
- **Type**: only two types exist — an option with a `BiosSettingPossibleValues`
  list is an `enumeration`; anything else is a `string`. There is no
  integer/ordered-list distinction in this format.
- `BiosSettingCurrentValue` → `current_value`; `BiosSettingPossibleValues` →
  `possible_values`. Remaining fields (`Description`, `BiosSettingReadOnly`,
  `BiosSettingId`, bounds, …) are kept verbatim in `metadata`.
- The **option identity** used for policy lookup = the normalized
  `vendor/option` path (after stripping the `/attributes/` class quirk),
  because plain option names could collide across vendors. A human-friendly
  `Name` is retained for reporting.

### Data types

| type | value sources | notes |
|------|---------------|-------|
| `enumeration` | `BiosSettingPossibleValues` + `BiosSettingCurrentValue` | main checkable type |
| `string` | `BiosSettingCurrentValue` | permitted as a string; no possible-values list |

## 2. Modular parser → internal data model

Keep parsing source-agnostic by translating to a neutral in-memory model.
Adds an HP/text representation later without touching the analyzer.

### Internal model (a dataclass per option)

- `path` (identity key, e.g. `hp-bioscfg/Secure Boot` — class quirk already stripped)
- `name` (human-friendly name / display_name if available, else leaf segment)
- `type`
- `possible_values`: `Optional[list[str]]` (from `possible_values`/`elements`)
- `current_value`: `Optional[str]`
- `metadata`: `dict` — all other keys (`min_length`, `upper_bound`, `display_name`, …) retained verbatim for future/reporting use
- The full raw path (e.g. `hp-bioscfg/attributes/Secure Boot`) is also kept
  (as `raw_path`) so reports can always map a policy key back to the sysfs file.

The parse layer reads one source format and produces a **list of these
records**. All policy logic operates only on this model.

### Parser design (pluggable)

- Base abstract parser interface: `parse(source) -> list[Option]`.
- `FwupdJsonParser` (fwupd `get-bios-settings` output), format name
  `fwupd-json`. Structured JSON, the recommended source. Two types only:
  enumeration (has `possible_values`) and string. Canonical key derived from
  each entry's `Filename` sysfs path (strip prefix and `/attributes/`, undo
  `!` → `/`).
- `HPSetupTxtParser` (HP `HPSetup.txt`-style reports), format name `hp-setup`,
  read by the same CLI with `--format` or auto-detected from the text.
- `SysfsDirParser` (a `/sys/class/firmware-attributes` directory or copy),
  format name `sysfs-dir`. Recursively descends `<vendor>/attributes/*`, reading
  each option's attribute files. Skips non-`attributes` classes and module-level
  scalars. Typing and canonical keys mirror the fwupd parser, so a directory
  and its `get-bios-settings` JSON reconcile identically.
- A registry / factory that selects a parser by input kind; `--format auto`
  (default) sniffs the text/file structure.
  - Directory input → `sysfs-dir`; JSON starting with `{` (fwupd) → `fwupd-json`;
    else HP Setup.
- Capabilities of the HP Setup parser:
  - `*`-prefixed value ⇒ enumeration (`possible_values` + `current_value`).
  - single unmarked value ⇒ scalar `string`/`integer` current.
  - multiple unmarked values ⇒ `ordered-list` (values = possible_values;
    current = `;`-joined list, mirroring the sysfs dump).
  - No vendor prefix in this format ⇒ namespaced under `hp-bioscfg/` to share
    policy keys with the sysfs model.

## 3. Policy database (JSON)

Text/JSON file, human-editable, keyed by option path.

```json
{
  "version": 1,
  "policy": {
    "hp-bioscfg/Secure Boot": {
      "accept": ["Enable"],
      "reject": ["Disable"]
    },
    "hp-bioscfg/Bluetooth": {
      "wildcard": true
    }
  }
}
```

- `accept`: values the current value / this option is allowed to be.
- `reject`: values not allowed.
- `wildcard: true`: any value is accepted; option is "don't care".
- Values not present in either list are **unknown** (see section 4).
- An option may list `accept` *and* `reject` values together (map each
  enumerated value to one of the two); a value must not appear in both lists
  (overlap ⇒ the loader rejects the DB / row as malformed, fail-closed).

## 4. Evaluation and reporting

For each option:

1. If option **not present** in policy ⇒ status `UNKNOWN_OPTION` → review.
2. If present with `wildcard: true` ⇒ `OK` (no per-value check).
3. Determine each `possible_value`'s classification: in `accept` / in `reject` / unknown.
4. If any `possible_value` is unknown ⇒ status `UNKNOWN_VALUE` → review
   (the current value may still be known, but the policy is incomplete).
5. If the *current value* is in `accept` ⇒ `OK`.
6. If the current value is in `reject` or not among `possible_values` ⇒ `VIOLATION`.

Notes on integer/string options: for v1, **all checkable types (including
`integer`) use plain value matching** — the concrete current value is classified
against `accept`/`reject` exactly like an enumeration value. Numeric range /
min-length constraints are out of scope for v1 but the schema can be extended
later.

Statuses: `OK`, `VIOLATION`, `UNKNOWN_OPTION`, `UNKNOWN_VALUE`
(and `IGNORED` for type-less metadata rows — not real options). A typed option
with no `current_value` in the dump is still evaluated (not ignored): with an
empty policy it is `UNKNOWN_OPTION`, and if policy-covered it is
`UNKNOWN_VALUE` (nothing to compare) unless wildcarded.

An option may carry **multiple** statuses at once — e.g. its current value is in
`reject` *and* another possible value is still unreviewed ⇒ report both
`VIOLATION` and `UNKNOWN_VALUE`. Statuses are an ordered per-option list, not a
single scalar.

### Output

- **stdout** — readable report table + per-status summary counts.
- **Text file copy** of the same report (path via CLI arg).
- **Review file** (see section 5) — only unknown options/values.

## 5. Review workflow

When unknown options/values are found, write a **review file** (JSON) mirroring
the policy shape — a `review` object keyed by option path, where each value is
an option dict with `accept`/`reject`/`wildcard` plus `current` and `unknown`,
so a reviewer edits it just like the policy file:

```json
{
  "version": 2,
  "review": {
    "hp-bioscfg/New Option": {
      "accept":  [],
      "current": "SomeValue",
      "unknown": ["OtherValue", "SomeValue"]
    }
  }
}
```

- Only options needing a decision appear. Set `wildcard: true` for "don't
  care", or move values into `accept`/`reject`. **`wildcard` is expected to be
  the most common case**, so it should be effortless to specify (see CLI below).
- The review file is also useful for browsing what the policy does *not*
  currently cover, so it doubles as the manual-review artifact.

### Policy update command

`policy update --review review.json --policy policy.json`:

- Applies each option's final `accept`/`reject` lists (or `wildcard`) to the
  policy. The reviewed lists **replace** any prior policy entry — they do not
  append to it (the review file is authoritative).
- `accept` → set the option's `accept` list (dedup); `reject` → set its `reject`
  list (dedup). Both lists can be set for the same option. A value in both
  lists is rejected as malformed. Lists are created empty if absent, which lets
  a reviewer explicitly clear a prior accepted value.
- `wildcard` → set the option to `wildcard: true`; any existing `accept`/`reject`
  lists for it are dropped (a wildcard supercedes per-value rules).
- An option left **fully undecided** (empty `accept`/`reject`, no `wildcard`) is
  **skipped silently** — no policy row is created/changed — and `policy update`
  reports how many were skipped. With `--wildcard-all`, every undecided option is instead
  promoted to a wildcard.
- For a brand-new option, a new policy row is created the first time a value is
  decided (this bootstraps options that were absent from the policy but seen in
  the dump).
- Writes the updated policy DB back (with a backup of the previous file).
- If all values of an option now fall in `accept` or `reject`, the DB row is
  complete; the option stops being flagged `UNKNOWN_VALUE`.

### Convention: review → accept/reject completeness

An option's set of `possible_values` may change between BIOS versions. The
analysis flags values drawn from the current dump's enumerable `possible_values`
set — including ones that are **not currently selected** as the current value —
so every newly-possible value must be explicitly mapped to `accept`/`reject`
(or the option wildcarded) to stop being flagged. The DB thus reflects what has
been encountered and reviewed; a value absent from the current dump's enum is
simply not evaluated.

## 6. CLI design (single script, subcommands)

```
fwsetup check         <dumpfile> [--policy POL] [--review REVIEW|auto]
fwsetup policy update --review REVIEW [--policy POL] [--backup]
fwsetup policy review --review REVIEW
fwsetup policy show   --policy POL [--show-wildcards last|inline|no] [--json OUT]
```

`check` is the default action:
- `--input` source dump path (mandatory).
- `--format`/auto-detect parser (`auto` is default; `sysfs-dir`,
  `fwupd-json`, `hp-setup`).
- `--policy` policy JSON database(s): a file, a comma-separated list, a directory
  (all `*.json`, non-recursive, sorted), or repeatable. Merged; a key appearing in
  more than one source is a conflict error.
- `--review` path for the review file (auto-named if omitted: `<input>.review.json`).
  (Save the stdout report with `| tee report.txt`; there is no `--report` flag.)

`policy update`:
- `--review`, `--policy` (default same policy), `--backup` to keep pre-merge copy.
- `--wildcard-all`: convenience flag — accept every not-yet-decided option as a
  wildcard (sets `wildcard: true` for its option). Since wildcard is the expected
  default for most options, this lets the user review only the few options that
  need an explicit `accept`/`reject` and wildcard the rest in one go.

`policy show`:
- `--policy` path to policy JSON (required); same multi-source rules as `check`
  (file, comma-separated, directory, or repeatable; merged with conflict errors).
- `--show-wildcards` `last|inline|no` (default `last`) controls how wildcard-only
  entries are displayed:
  - `last` — non-wildcard entries first (sorted by key), then wildcarded entries
    grouped at the end (sorted by key among themselves).
  - `inline` — keep all entries sorted by key together.
  - `no` — omit wildcard-only entries entirely.
- Each option is printed as a block showing its `accept` and `reject` values (or
  `wildcard: true`).
- `--json OUT` also writes the *policy itself* as JSON (version 1 format), with
  options ordered per `--show-wildcards` (so `no` omits wildcard-only entries).

`policy review`:
- `--review` path to a review JSON file, edited in place.
- Full-screen curses editor. `n`/`p` walk the options; within an option `j`/`k`
  (or arrows) move the highlight over its sorted values (initial highlight = the
  `current` value if present).
- `+`/`-`/`Space` classify the highlighted value as accepted/rejected/undecided;
  `*` accepts it exclusively (rejects all the rest). `Esc` resets the current
  option to its on-disk state. `q` saves and quits; `x` quits discarding changes
  (after confirmation).
- Core edit state is terminal-independent (`uefi_policy/review.py`) and tested
  without a TTY; the curses loop is a thin dispatch layer (`review_ui.py`).

## 7. Suggested file layout

```
scripts/
  uefi_policy/
    __init__.py
    model.py          # Option dataclass, Policy, status enums
    parsers/
      __init__.py     # registry/factory
      fwupd_json.py   # FwupdJsonParser
      hpsetup_txt.py  # HPSetupTxtParser
      sysfs_dir.py    # SysfsDirParser
    policy.py         # load/save/validate policy DB, review DB
    analyze.py        # evaluation logic
    reports.py        # stdout + file report formatting
    cli.py            # argparse dispatch
  fwsetup # thin entry point -> uefi_policy.cli.main()
  tests/
    test_parsers.py
    test_analyze.py
    test_policy.py
    data/…             # trimmed sample fixture
```

## 8. Open decisions / notes

- **Value matching is exact/verbatim** (preserving `\n\t` etc.). Wildcards are
  only at the option level (whole option "don't care"). Per-value glob/regex is
  out of scope for v1 but the policy JSON schema can be extended later.
- **Canonical names use `/`.** HP exposes `/` in option names as `!` in the
  sysfs dump (because `/` is forbidden in filenames). The sysfs parser undoes
  this (`!` → `/`) so both the sysfs dump and the HP Setup report reconcile to
  the same identity key.
- **Font / display name handling**: option may look empty in `attributes`
  (`pending_reboot`). Such metadata rows are recorded but not policy-checked.
- **Multiple vendors**: the path prefix (`hp-bioscfg/…`) keeps policy entries
  namespaced, so a policy can cover several vendors or hardware without clashes.
- Integration with Chipsec is out of scope here (plan targets the analyzer only).
