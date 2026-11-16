"""Load, validate, save and merge the policy DB and review DB."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List

POLICY_VERSION = 1
REVIEW_VERSION = 1

# Valid review decisions.
DECISION_REVIEW = "review"
DECISION_ACCEPT = "accept"
DECISION_REJECT = "reject"
DECISION_WILDCARD = "wildcard"
VALID_DECISIONS = (DECISION_REVIEW, DECISION_ACCEPT, DECISION_REJECT, DECISION_WILDCARD)


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


def load_policy(path: str) -> Policy:
    if not os.path.exists(path):
        raise PolicyError(f"policy file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
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
class ReviewEntry:
    path: str
    value: str
    decision: str = DECISION_REVIEW

    def to_dict(self) -> dict:
        return {"path": self.path, "value": self.value, "decision": self.decision}


def _validate_review_entry(d: dict) -> ReviewEntry:
    if not isinstance(d, dict):
        raise PolicyError("review entry is not a JSON object")
    path = d.get("path")
    value = d.get("value")
    decision = d.get("decision", DECISION_REVIEW)
    if not isinstance(path, str) or not path:
        raise PolicyError(f"review entry missing 'path': {d!r}")
    if not isinstance(decision, str) or decision not in VALID_DECISIONS:
        raise PolicyError(
            f"review entry for '{path}': invalid decision {decision!r}; "
            f"expected one of {VALID_DECISIONS}"
        )
    return ReviewEntry(path=path, value=value if value is not None else "", decision=decision)


def load_review(path: str) -> List[ReviewEntry]:
    if not os.path.exists(path):
        raise PolicyError(f"review file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise PolicyError(f"{path}: missing 'entries' list")
    return [_validate_review_entry(e) for e in entries]


def save_review(entries: List[ReviewEntry], path: str) -> None:
    data = {
        "version": REVIEW_VERSION,
        "entries": [e.to_dict() for e in entries],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _dedup(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def merge_review(policy: Policy, entries: List[ReviewEntry], wildcard_all: bool = False) -> int:
    """Apply review decisions to the policy. Returns number of applied entries."""
    applied = 0
    for entry in entries:
        decision = DECISION_WILDCARD if (wildcard_all and entry.decision == DECISION_REVIEW) else entry.decision
        if decision == DECISION_REVIEW:
            raise PolicyError(
                f"review entry for '{entry.path}' value {entry.value!r} is still 'review'; "
                "resolve to accept/reject/wildcard before merging"
            )
        entry_obj = policy.entries.setdefault(entry.path, PolicyEntry())
        if decision == DECISION_WILDCARD:
            entry_obj.accept = []
            entry_obj.reject = []
            entry_obj.wildcard = True
        elif decision == DECISION_ACCEPT:
            entry_obj.accept = _dedup(entry_obj.accept + [entry.value])
        elif decision == DECISION_REJECT:
            entry_obj.reject = _dedup(entry_obj.reject + [entry.value])
        else:  # pragma: no cover - guarded by validation
            raise PolicyError(f"bad decision: {decision}")
        applied += 1
    return applied
