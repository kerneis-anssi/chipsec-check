# UEFI Configuration Policy Analyzer

Analyze a UEFI configuration dump against a policy database, report
violations, and drive a manual review → merge workflow.

Full design notes: see `PLAN.md`. Progress: see `PROGRESS.md`.

## Overview

```
check         <dumpfile> --policy POLICY [--report OUT] [--review REVIEW]
policy merge  --review REVIEW --policy POLICY [--wildcard-all] [--backup]
policy show   --policy POLICY [--show-wildcards last|inline|no]
```

1. `check` parses the configuration dump, evaluates each option against the
   policy, prints a report to stdout (+ a text copy via `--report`), and writes
   a **review file** listing every option the policy doesn't fully cover yet.
2. A human edits the review file, moving values into `accept`/`reject` (or set
   `wildcard: true`) for each option.
3. `policy merge` applies those decisions to the policy database.

`--policy` (on `check` and `policy show`) may be a single file, a comma-separated
list of files, a directory (all `*.json` inside, non-recursively, sorted), or be
repeated. Entries are merged; a given option key must appear in at most one
source, otherwise loading fails with a conflict error. (`policy merge` requires
a single policy file, which it updates in place.)

## Quick start

```
# Dump the configuration (run on the target system)
fwupdmgr get-bios-settings > bios-settings.json

# Analyze against an existing policy
python3 fwsetup check bios-settings.json \
    --policy policy.json --report report.txt --review review.json

# Edit review.json: move values into "accept" / "reject",
# or set "wildcard": true to accept any value for that option.

# Apply the reviewed decisions to the policy
python3 fwsetup policy merge --review review.json --policy policy.json --backup

# Pretty-print the policy (grouped values per option; wildcards last)
fwsetup policy show --policy policy.json

# Omit wildcard-only entries, or keep them inline, respectively:
fwsetup policy show --policy policy.json --show-wildcards no
fwsetup policy show --policy policy.json --show-wildcards inline

# Also write the policy as JSON (ordered per --show-wildcards):
fwsetup policy show --policy policy.json --json out.json
```

## Input formats

The analyzer can read three kinds of input (auto-detected, or force with
`--format`):

- **fwupd JSON** (`fwupd-json`) — structured output from fwupd's
  `get-bios-settings` (`fwupdmgr get-bios-settings`). A `{"BiosSettings": [...]}`
  list; options with a `BiosSettingPossibleValues` are `enumeration`, the rest
  `string`. Recommended source.
- **Sysfs directory** (`sysfs-dir`) — pass a `/sys/class/firmware-attributes`
  directory (or a copy of it). The parser descends `<vendor>/attributes/*` and
  reads each option's attribute files. Typing and canonical keys are identical
  to the fwupd JSON parser, so the two reconcile.
- **HP Setup report** (`hp-setup`) — an `HPSetup.txt`-style host report: option
  name lines followed by tab-indented value lines. In an enumeration the
  applied value is marked with `*`; scalar options list a single value; ordered
  lists list all elements. Options are namespaced `hp-bioscfg/<name>` to share
  policy keys with the fwupd model. UTF-16/CRLF files are handled automatically.

All formats reconcile to the same policy keys: HP names options with `/` (e.g.
`Save/Restore GPT`), while the fwupd/sysfs names escape `/` as `!` for FAT32
compatibility (`Save!Restore GPT`); the parsers canonicalize that back to `/`
so a single policy works across sources.

## Policy database (`policy.json`)

A JSON object keyed by normalized option path (the Linux `/attributes/` class
segment is stripped, so `hp-bioscfg/attributes/Secure Boot` is keyed
`hp-bioscfg/Secure Boot`). Each entry holds accepted (`accept`) and/or rejected
(`reject`) values, or a `wildcard` flag meaning "don't care" (any value OK).

```json
{
  "version": 1,
  "policy": {
    "hp-bioscfg/Secure Boot": { "accept": ["Enable"] },
    "hp-bioscfg/Bluetooth":    { "reject": ["Enable"] },
    "hp-bioscfg/TPM Device":   { "wildcard": true }
  }
}
```

Rules:
- An option may list accepted (`accept`) *and/or* rejected (`reject`) values;
  for an enumeration you typically map every value to one of the two.
- A value must not appear in both `accept` and `reject`.
- Values in the dump not in either list are **unknown** → flagged for review.
- An option absent from the policy entirely is **unknown** → flagged for review.

## Evaluation statuses

- `OK`            — current value is explicitly accepted (or option is wildcard).
- `VIOLATION`     — current value is explicitly rejected (or nothing is accepted).
- `UNKNOWN_OPTION`— option not present in the policy.
- `UNKNOWN_VALUE` — option is present but some value isn't covered yet.
- `IGNORED`       — not a real option (no `type`, e.g. a metadata row).

An option can carry several statuses at once (e.g. `VIOLATION` + `UNKNOWN_VALUE`)
when the current value is rejected while other values remain unreviewed.

## Review workflow

The review file mirrors the policy format: a `review` object keyed by option
path, where each entry is an option dict with `accept`, `reject`, `wildcard`,
plus `current` (the observed value) and `unknown` (values not yet decided). The
reviewer just moves values between `accept`/`reject` (or sets `wildcard: true`
for "don't care") — exactly as they would in the policy file.

```json
{
  "version": 2,
  "review": {
    "hp-bioscfg/Secure Boot": {
      "accept":  ["Enable"],
      "current": "Enable",
      "unknown": ["Disable"]
    },
    "hp-bioscfg/Bluetooth": {
      "reject":  ["Enable"],
      "current": "Enable",
      "unknown": ["Disable"]
    },
    "hp-bioscfg/TPM Device": {
      "wildcard": true,
      "current":  "Enable",
      "unknown":  ["Disable", "Enable"]
    }
  }
}
```

Only options still needing a decision appear. `unknown` lists every enumerated
value (or the current value, for a scalar) not yet covered by `accept`/`reject`
— not just the currently-selected value — so a value is only "retired" once you
explicitly move it into `accept` or `reject` (or wildcard the option). `policy merge`
applies each option's final `accept`/`reject` lists (or `wildcard`) to the
policy — the reviewed lists **replace** any prior policy entry, they don't
merge. An option the
reviewer leaves fully undecided (empty `accept`/`reject` and no `wildcard`) is
**skipped silently** (no policy entry is created/changed), and `policy merge`
reports how many were skipped. With `--wildcard-all`, every undecided option is instead
promoted to a wildcard — handy since wildcard is the common case.

`policy merge` creates new policy rows for options previously unknown, so accepting a
value for a brand-new option bootstraps it into the policy.

## Tests

```
python3 -m unittest discover -s tests -v
```
