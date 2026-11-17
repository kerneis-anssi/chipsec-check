"""Load, validate, save and merge the policy DB and review DB."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

POLICY_VERSION = 1
REVIEW_VERSION = 2


class PolicyError(Exception):
    """Raised for malformed policy or review data."""


@dataclass
class PolicyEntry:
    """Policy for a single option."""

    accept: List[str] = field(default_factory=list)
    reject: List[str] = field(default_factory=list)
    wildcard: bool = False

    def to_dict(self) -> dict:
        d: dict = {}
        if self.wildcard:
            d["wildcard"] = True
        if self.accept:
            d["accept"] = list(self.accept)
        if self.reject:
            d["reject"] = list(self.reject)
        return d


@dataclass
class Policy:
    """In-memory policy database keyed by normalized option path."""

    entries: Dict[str, PolicyEntry] = field(default_factory=dict)

    def get(self, path: str) -> PolicyEntry:
        return self.entries.get(path)

    def has(self, path: str) -> bool:
        return path in self.entries

    def to_dict(self) -> dict:
        return {p: e.to_dict() for p, e in sorted(self.entries.items())}


def _validate_policy_entry(path: str, d: dict) -> PolicyEntry:
    if not isinstance(d, dict):
        raise PolicyError(f"policy entry for '{path}' is not a JSON object")
    accept = d.get("accept", [])
    reject = d.get("reject", [])
    wildcard = d.get("wildcard", False)
    if not isinstance(accept, list) or not isinstance(reject, list):
        raise PolicyError(f"policy entry for '{path}': accept/reject must be lists")
    if not all(isinstance(v, str) for v in accept) or not all(isinstance(v, str) for v in reject):
        raise PolicyError(f"policy entry for '{path}': accept/reject must contain only strings")
    if accept and reject:
        raise PolicyError(
            f"policy entry for '{path}': accept and reject are mutually exclusive"
        )
    return PolicyEntry(accept=accept, reject=reject, wildcard=bool(wildcard))


def _load_json(path: str) -> object:
    """Read and parse a JSON file, wrapping failures into a PolicyError.

    Catches empty files, invalid JSON, decode errors and I/O errors so callers
    get a clear, actionable message instead of a raw exception.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot read {path}: {exc}") from exc
    text = text.strip()
    if not text:
        raise PolicyError(f"{path}: file is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{path}: invalid JSON ({exc})") from exc


def load_policy(path: str) -> Policy:
    if not os.path.exists(path):
        raise PolicyError(f"policy file not found: {path}")
    data = _load_json(path)
    entries_section = data.get("policy") if isinstance(data, dict) else None
    if not isinstance(entries_section, dict):
        raise PolicyError(f"{path}: missing 'policy' object")
    policy = Policy()
    for option_path, entry in entries_section.items():
        policy.entries[option_path] = _validate_policy_entry(option_path, entry)
    return policy


def save_policy(policy: Policy, path: str, backup: bool = False) -> None:
    if backup and os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    data = {"version": POLICY_VERSION, "policy": policy.to_dict()}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


@dataclass
class ReviewOption:
    """Review state for a single option, mirroring a policy entry.

    Mirrors the policy shape (accept/reject/wildcard) so a reviewer edits the
    review file just like the policy: move values between ``accept`` and
    ``reject`` (and can set ``wildcard: true``). ``current`` is the option's
    current value from the dump; ``unknown`` lists values not yet decided.
    Only options needing review are present.
    """

    path: str
    accept: List[str] = field(default_factory=list)
    reject: List[str] = field(default_factory=list)
    wildcard: bool = False
    current: Optional[str] = None
    unknown: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {}
        # Always include accept/reject (even empty) so a reviewer can see both
        # targets and cut/paste values between them.
        d["accept"] = list(self.accept)
        d["reject"] = list(self.reject)
        if self.wildcard:
            d["wildcard"] = True
        if self.current is not None:
            d["current"] = self.current
        if self.unknown:
            d["unknown"] = list(self.unknown)
        return d


def _str_list(items) -> List[str]:
    """Validate a JSON value is a list of strings; returns it."""
    if not isinstance(items, list) or not all(isinstance(v, str) for v in items):
        raise PolicyError(f"expected a list of strings, got {items!r}")
    return list(items)


def _validate_review_option(path: str, d: dict) -> ReviewOption:
    if not isinstance(d, dict):
        raise PolicyError(f"review entry for '{path}' is not a JSON object")
    accept = _str_list(d.get("accept", []))
    reject = _str_list(d.get("reject", []))
    unknown = _str_list(d.get("unknown", []))
    wildcard = bool(d.get("wildcard", False))
    current = d.get("current")
    if current is not None and not isinstance(current, str):
        raise PolicyError(f"review entry for '{path}': 'current' must be a string")
    return ReviewOption(
        path=path,
        accept=accept,
        reject=reject,
        wildcard=wildcard,
        current=current,
        unknown=unknown,
    )


def load_review(path: str) -> List[ReviewOption]:
    if not os.path.exists(path):
        raise PolicyError(f"review file not found: {path}")
    data = _load_json(path)
    options = data.get("review") if isinstance(data, dict) else None
    if not isinstance(options, dict):
        raise PolicyError(f"{path}: missing 'review' object")
    return [_validate_review_option(p, d) for p, d in sorted(options.items())]


def _format_review(data: dict) -> str:
    """Serialize the review DB to JSON, expanding empty arrays.

    An empty ``accept``/``reject`` array is written with ``[`` and ``]`` on
    their own lines so a reviewer can cut/paste values between them without
    editing a ``[]`` token:
    ``"reject": [``, then ``],`` on the next line.
    """
    blob = json.dumps(data, indent=2, ensure_ascii=False)
    lines = blob.splitlines()
    out: List[str] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith(": [],"):
            indent = line[: len(line) - len(line.lstrip())]
            opener = stripped[: -len(" [],")] + " ["
            out.append(opener)
            out.append(indent + "],")
        else:
            out.append(line)
    return "\n".join(out)


def save_review(options: List[ReviewOption], path: str) -> None:
    data = {
        "version": REVIEW_VERSION,
        "review": {o.path: o.to_dict() for o in options},
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_format_review(data))
        fh.write("\n")


def _dedup(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def merge_review(policy: Policy, options: List[ReviewOption], wildcard_all: bool = False) -> tuple:
    """Apply reviewed options to the policy.

    Returns (applied, skipped): how many options were applied versus skipped
    (left fully undecided — empty accept/reject and no wildcard).
    """
    applied = 0
    skipped = 0
    for option in options:
        decided = bool(option.accept or option.reject or option.wildcard)
        if not decided and not wildcard_all:
            skipped += 1
            continue
        entry_obj = policy.entries.setdefault(option.path, PolicyEntry())
        if wildcard_all and not decided:
            entry_obj.accept = []
            entry_obj.reject = []
            entry_obj.wildcard = True
        elif option.wildcard:
            entry_obj.accept = []
            entry_obj.reject = []
            entry_obj.wildcard = True
        elif option.accept:
            if option.reject:
                raise PolicyError(
                    f"review entry for '{option.path}': accept and reject are "
                    "mutually exclusive"
                )
            entry_obj.accept = _dedup(option.accept)
            entry_obj.reject = []
            entry_obj.wildcard = False
        elif option.reject:
            entry_obj.reject = _dedup(option.reject)
            entry_obj.accept = []
            entry_obj.wildcard = False
        applied += 1
    return applied, skipped
