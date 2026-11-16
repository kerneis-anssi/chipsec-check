# UEFI Configuration Policy Analyzer — Design Plan

A Python tool that parses UEFI configuration dumps, evaluates them against a
policy database, reports violations, and supports a review/merge workflow for
options and values not yet covered by the policy.

## 1. Input data format (sysfs dump)

A text file produced by:

```
grep -R . /sys/class/firmware-attributes/ | cut -d/ -f5- > firmware-attributes.txt
```

Each line has the form:

```
<vendor>/<class>/<option>/<key>:<value>
```

Concrete example from the sample (`bios/firmware-attributes.txt`):

```
hp-bioscfg/attributes/Secure Boot/type:enumeration
hp-bioscfg/attributes/Secure Boot/possible_values:Disable;Enable
hp-bioscfg/attributes/Secure Boot/current_value:Enable
```

### Parsing rules / gotchas observed in the sample

- The **key** is the segment after the last `/` up to the first `:`.
- The **value** is everything after that first `:`, and may itself contain
  colons (`current_value:HDD:M.2:1;...`, `OS Recovery Agent Public Key/current_value:v02...==`).
  ⇒ Split each line into `(path, key, value)` on the *first* colon only.
- Option *names* may contain literal `\n\t` escape sequences (e.g. `HP_Disk0MapForUefiBootOrder/current_value` contains `PciRoot...\n\tPci(0x14...)`). These are single physical lines, so no multi-line reassembly is required — but the `\t` and `\n` must be preserved verbatim if a value must be matched.
- Prefixes seen in the sample: `attributes`, `authentication`, `power`. There is also a module-level top entry (`hp-bioscfg/attributes/pending_reboot:0`) that has an empty option name.
- Some options are metadata-only and lack a `current_value` (e.g. have `max_length`, `min_length`, `lower_bound`, `upper_bound` but no `current_value`). These are fine to carry but are not policy-checked.
- **Key normalization (Linux quirk):** the middle `/attributes/` class segment is an
  always-present Linux sysfs detail with no policy meaning. The parser strips it
  from the identity key, so a dump line `hp-bioscfg/attributes/Secure Boot` maps
  to option identity **`hp-bioscfg/Secure Boot`**. Other, vendor-specific class
  segments (e.g. `authentication`, `power`) are preserved. The set of segments to
  strip is parser/config driven (default: `{"attributes"}`) so it can be adapted.
- The **option identity** used for policy lookup = the normalized
  `vendor/option` path (after stripping the Linux class quirk, and excluding the
  key), because plain option names could collide across vendors. A human-friendly
  `display_name` is retained for reporting.

### Data types seen

| `type`  | value sources | notes |
|---------|---------------|-------|
| `enumeration` | `possible_values` (`;`-separated) + `current_value` | main checkable type |
| `ordered-list` | `elements` + `current_value` | treat like an enumeration for policy matching |
| `integer` | `lower_bound`/`upper_bound`/`scalar_increment` + `current_value` | optional range check |
| `string` | `min_length`/`max_length` + `current_value` | usually not policy-checked; often informational |

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
- `SysfsTxtParser` (this task).
- A registry / factory that selects a parser by input kind so an HP/other text
  parser can be added later with no changes to the analyzer.

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
- Convention: `accept` and `reject` are mutually exclusive for the same option;
  if both are present, `reject` wins (fail-closed), or the loader may reject the
  DB as malformed. Decision: **loader warns and treats such a row as invalid**, fail-closed.

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
(and `IGNORED` for metadata-only options with no `current_value`, excluded from checks).

An option may carry **multiple** statuses at once — e.g. its current value is in
`reject` *and* another possible value is still unreviewed ⇒ report both
`VIOLATION` and `UNKNOWN_VALUE`. Statuses are an ordered per-option list, not a
single scalar.

### Output

- **stdout** — readable report table + per-status summary counts.
- **Text file copy** of the same report (path via CLI arg).
- **Review file** (see section 5) — only unknown options/values.

## 5. Review workflow

When unknown options/values are found, write a **review file** (JSON), one entry
per unknown `(path, value)` combination, each carrying a decision field:

```json
{
  "version": 1,
  "entries": [
    {
      "path": "hp-bioscfg/New Option",
      "value": "SomeValue",
      "decision": "review"      // "review" | "accept" | "reject"
    }
  ]
}
```

- Default decision is `review`.
- A human edits `decision` to `accept` or `reject` for each line, optionally
  deleting rows they do not want to add.
- The review file is also useful for browsing what the policy does *not*
  currently cover, so it doubles as the manual-review artifact.

### Merge command

`merge-review --review review.json --policy policy.json`:

- For each entry with decision `review` → error / refuse (must be resolved).
- `accept` → add value to `accept` list (dedup).
- `reject` → add value to `reject` list (dedup).
- Skips entries whose option path does not exist in the source dump — unless
  the value is for a brand-new option, in which case a new policy row is created
  (this bootstraps options that were absent from the policy but seen in the dump).
- Writes the updated policy DB back (with a backup of the previous file).
- If all values of an option now fall in `accept` or `reject`, the DB row is
  complete; the option stops being flagged `UNKNOWN_VALUE`.

### Convention: review → accept/reject completeness

An option's set of `possible_values` may change between BIOS versions. The
analysis only flags values present in the *current* dump. This is documented as
a known limitation — the DB reflects what has been encountered and reviewed.

## 6. CLI design (single script, subcommands)

```
analyze_uefi_cfg.py dump     <dumpfile> [--policy POL] [--report OUT] [--review REVIEW|auto]
analyze_uefi_cfg.py merge    --review REVIEW [--policy POL] [--backup]
```

`dump` is the default action:
- `--input` source dump path (mandatory).
- `--format`/auto-detect parser.
- `--policy` path to policy JSON (required).
- `--report` path for the text report copy (in addition to stdout).
- `--review` path for the review file (auto-named if omitted: `<dump>.review.json`).

`merge`:
- `--review`, `--policy` (default same policy), `--backup` to keep pre-merge copy.

## 7. Suggested file layout

```
scripts/
  uefi_policy/
    __init__.py
    model.py          # Option dataclass, Policy, status enums
    parsers/
      __init__.py     # registry/factory
      sysfs_txt.py    # SysfsTxtParser
    policy.py         # load/save/validate policy DB, review DB
    analyze.py        # evaluation logic
    reports.py        # stdout + file report formatting
    cli.py            # argparse dispatch
  analyze_uefi_cfg.py # thin entry point -> uefi_policy.cli.main()
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
- **Font / display name handling**: option may look empty in `attributes`
  (`pending_reboot`). Such metadata rows are recorded but not policy-checked.
- **Multiple vendors**: the path prefix (`hp-bioscfg/…`) keeps policy entries
  namespaced, so a policy can cover several vendors or hardware without clashes.
- Integration with Chipsec is out of scope here (plan targets the analyzer only).
