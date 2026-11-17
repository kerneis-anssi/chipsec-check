# UEFI Configuration Policy Analyzer

Analyze a UEFI configuration dump against a policy database, report
violations, and drive a manual review → merge workflow.

Full design notes: see `PLAN.md`. Progress: see `PROGRESS.md`.

## Overview

```
dump   <dumpfile> --policy POLICY [--report OUT] [--review REVIEW]
merge  --review REVIEW --policy POLICY [--wildcard-all] [--backup]
```

1. `dump` parses the configuration dump, evaluates each option against the
   policy, prints a report to stdout (+ a text copy via `--report`), and writes
   a **review file** listing every option/value the policy doesn't cover yet.
2. A human edits the review file, assigning each entry a `decision`
   (`accept` | `reject` | `wildcard`).
3. `merge` applies those decisions to the policy database.

## Quick start

```
# Dump the configuration (run on the target system)
grep -R . /sys/class/firmware-attributes/ | cut -d/ -f5- > firmware-attributes.txt

# Analyze against an existing policy
python3 analyze_uefi_cfg.py dump firmware-attributes.txt \
    --policy policy.json --report report.txt --review review.json

# Edit review.json: set decision: "accept" | "reject" | "wildcard"

# Apply the reviewed decisions to the policy
python3 analyze_uefi_cfg.py merge --review review.json --policy policy.json --backup
```

## Input formats

The analyzer can read three dump formats (auto-detected, or force with
`--format`):

- **fwupd JSON** (`fwupd-json`) — structured output from fwupd's
  `get-bios-settings` (`fwupdmgr get-bios-settings`). A `{"BiosSettings": [...]}`
  list; options with a `BiosSettingPossibleValues` are `enumeration`, the rest
  `string`. Recommended: same content as the grep dump but structured.
- **sysfs dump** (`sysfs-txt`) — the `grep -R . /sys/class/firmware-attributes/`
  text. Deprecated (see below).
- **HP Setup report** (`hp-setup`) — an `HPSetup.txt`-style host report: option
  name lines followed by tab-indented value lines. In an enumeration the
  applied value is marked with `*`; scalar options list a single value; ordered
  lists list all elements. Options are namespaced `hp-bioscfg/<name>` to share
  policy keys with the fwupd model. UTF-16/CRLF files are handled automatically.

All formats reconcile to the same policy keys: HP names options with `/` (e.g.
`Save/Restore GPT`), while the sysfs/fwupd name escapes `/` as `!` for FAT32
compatibility (`Save!Restore GPT`); the parsers canonicalize that back to `/`
so a single policy works across sources. The grep-based `sysfs-txt` parser is
legacy and superseded by `fwupd-json`.

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
- `accept` and `reject` are mutually exclusive for a single option.
- Values not in either list are **unknown** → flagged for review.
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

The review file contains one entry per unknown `(path, value)`, each with a
`decision`:

```json
{
  "version": 1,
  "entries": [
    { "path": "hp-bioscfg/Secure Boot", "value": "Disable", "decision": "review" }
  ]
}
```

Default `decision` is `review`. Edit it to `accept`, `reject`, or `wildcard`
(whole option "don't care"). With `--wildcard-all`, every still-`review` entry
is treated as a wildcard during merge — handy since wildcard is the common case.

`merge` creates new policy rows for options previously unknown, so accepting a
value for a brand-new option bootstraps it into the policy.

## Tests

```
python3 -m unittest discover -s tests -v
```
