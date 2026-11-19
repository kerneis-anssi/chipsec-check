"""Evaluation: compare parsed options against a policy and classify."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from uefi_policy.model import Option, Result, Status
from uefi_policy.policy import Policy, PolicyEntry, ReviewOption


def _option_values(option: Option) -> List[str]:
    """The value universe: enumerable values, else the current (single) value."""
    if option.possible_values:
        return option.possible_values
    if option.current_value is not None:
        return [option.current_value]
    return []


def _classify_values(entry: PolicyEntry, values: Sequence[str]) -> Tuple[List[str], List[str], List[str]]:
    """Split values into (accepted, rejected, unknown) for a policy entry."""
    accept = set(entry.accept)
    reject = set(entry.reject)
    accepted = [v for v in values if v in accept]
    rejected = [v for v in values if v in reject]
    unknown = [v for v in values if v not in accept and v not in reject]
    return accepted, rejected, unknown


def _unknown_values(option: Option, entry: Optional[PolicyEntry]) -> List[str]:
    """Values of this option not covered by accept/reject.

    Covers the enumerable values (possible_values/elements) *and* the current
    value even when it is not part of the enumerable set.
    """
    values = list(set(_option_values(option)))
    if option.current_value is not None:
        values.append(option.current_value)
    if entry is None:
        return _dedup(values)
    _, _, unknown = _classify_values(entry, values)
    return _dedup(unknown)


def _dedup(values: Sequence[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def evaluate_option(option: Option, policy: Policy) -> Result:
    result = Result(option=option)
    # An unreadable attribute (e.g. /sys permission denied) must surface
    # regardless of the evaluation branches below.
    if option.denied:
        result.statuses.append(Status.DENIED)
    if not option.is_policy_checkable:
        # Pure metadata row (no type): not a real option, skip it.
        result.statuses.append(Status.IGNORED)
        return result

    entry = policy.get(option.path)
    if entry is None:
        result.statuses.append(Status.UNKNOWN_OPTION)
        return result

    if entry.wildcard:
        result.statuses.append(Status.OK)
        return result

    current = option.current_value
    known = set(entry.accept) | set(entry.reject)

    if current is None:
        # A typed option with no current value in the dump. It is covered by
        # the policy but there is nothing to compare: flag for review rather
        # than silently ignoring it.
        result.statuses.append(Status.UNKNOWN_VALUE)
        return result

    if current in set(entry.reject):
        result.statuses.append(Status.VIOLATION)
    elif current in set(entry.accept):
        result.statuses.append(Status.OK)
    else:
        # Current value is not covered by accept/reject: needs review, not a
        # hard violation (it's unknown, not explicitly forbidden). If nothing
        # at all is accepted, still pragmatically a violation (fail-closed).
        if not set(entry.accept):
            result.statuses.append(Status.VIOLATION)
        result.statuses.append(Status.UNKNOWN_VALUE)

    # Completeness: any enumerable value not covered by the policy.
    if unknown_values := [v for v in _option_values(option) if v not in known]:
        result.statuses.append(Status.UNKNOWN_VALUE)

    return result


def evaluate(options: Sequence[Option], policy: Policy) -> List[Result]:
    return [evaluate_option(o, policy) for o in options]


def gather_review(results: Sequence[Result], policy: Policy) -> List[ReviewOption]:
    """Collect review state for options needing manual review.

    Returns one ``ReviewOption`` per option to review (mimicking a policy entry):
    - ``accept``/``reject`` carry the option's current policy state (if any).
    - ``current`` is the observed current value from the dump.
    - ``unknown`` lists the values not covered by accept/reject (to move into
      ``accept``/``reject`` when reviewed).

    Only options flagged UNKNOWN_OPTION or UNKNOWN_VALUE (with nothing decided)
    that still need review are returned.
    """
    options: List[ReviewOption] = []
    for r in results:
        needs_review = (Status.UNKNOWN_OPTION in r.statuses
                        or Status.UNKNOWN_VALUE in r.statuses)
        if not needs_review or Status.IGNORED in r.statuses:
            continue
        entry = policy.get(r.option.path)
        accept = list(entry.accept) if entry else []
        reject = list(entry.reject) if entry else []
        unknown = _unknown_values(r.option, entry)
        if not unknown and r.option.current_value is not None:
            # Current value is the only value to review; surface it.
            unknown = [r.option.current_value]
        options.append(
            ReviewOption(
                path=r.option.path,
                accept=accept,
                reject=reject,
                current=r.option.current_value,
                unknown=_dedup(unknown),
            )
        )
    return options
