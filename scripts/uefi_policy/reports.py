"""Report formatting: produce a human-readable table + summary counts."""

from __future__ import annotations

from typing import IO, List, Sequence, Tuple

from uefi_policy.model import Result, Status
from uefi_policy.policy import Policy, PolicyEntry

_ORDER = [Status.VIOLATION, Status.DENIED, Status.UNKNOWN_OPTION, Status.UNKNOWN_VALUE, Status.OK, Status.IGNORED]


def _drop_vendor(path: str) -> str:
    """Return the option key without its vendor prefix (first path segment)."""
    return path.split("/", 1)[-1]


def _truncate(text: str, width: int) -> str:
    """Truncate *text* to *width*, with the ellipsis overriding the last 3
    characters so the result is no longer than *width* (keeps column alignment)."""
    if width <= 0:
        return ""
    if width < 3 or len(text) <= width:
        return text[:width]
    return text[: width - 3] + "..."


def build_report(results: Sequence[Result]) -> str:
    lines: List[str] = []
    lines.append(f"{'OPTION':<50} {'CURRENT':<40} STATUS")
    lines.append("-" * 100)
    by_status: dict = {}
    for result in results:
        status = result.primary_status
        current = _truncate(
            (result.option.current_value or "").replace("\n", "\\n"), 40
        )
        path = _truncate(_drop_vendor(result.option.path), 50)
        lines.append(f"{path:<50} {current:<40} {status.value}")
        by_status[status] = by_status.get(status, 0) + 1

    lines.append("")
    lines.append("Summary:")
    for status in _ORDER:
        if status in by_status:
            lines.append(f"  {status.value:<16} {by_status[status]}")

    violations = [r for r in results if Status.VIOLATION in r.statuses]
    if violations:
        lines.append("")
        lines.append("Violations:")
        for r in violations:
            current = (r.option.current_value or "").replace("\n", "\\n")
            key = _drop_vendor(r.option.path)
            lines.append(f"  {key}: {current}")
    return "\n".join(lines)


def write_report(report: str, stream: IO[str]) -> None:
    stream.write(report + "\n")


def ordered_entries(policy: Policy, show_wildcards: str = "last") -> List[Tuple[str, PolicyEntry]]:
    """Return the policy entries ordered per the ``show_wildcards`` mode.

    Base order is by key. ``show_wildcards``:
      - ``last`` (default): group wildcard-only entries at the end, sorted by
        key among themselves; non-wildcard entries lead, sorted by key.
      - ``inline``: keep everything sorted by key together.
      - ``no``: drop wildcard-only entries entirely.
    """
    entries: List[Tuple[str, PolicyEntry]] = sorted(policy.entries.items())
    if show_wildcards == "no":
        return [kv for kv in entries if not kv[1].wildcard]
    if show_wildcards == "last":
        normal = [kv for kv in entries if not kv[1].wildcard]
        wildcards = [kv for kv in entries if kv[1].wildcard]
        return normal + wildcards
    return entries  # "inline"


def format_policy(policy: Policy, show_wildcards: str = "last") -> str:
    """Pretty-print a policy database for terminal display.

    For each key, show its accepted and rejected values (or ``wildcard``).
    ``show_wildcards`` controls how wildcard-only entries are ordered; see
    :func:`ordered_entries`.
    """
    blocks = ["\n".join(_policy_entry_lines(key, entry))
              for key, entry in ordered_entries(policy, show_wildcards)]
    return "\n\n".join(blocks)


def _policy_entry_lines(key: str, entry: PolicyEntry) -> List[str]:
    lines = [f"{key}:"]
    if entry.wildcard:
        lines.append("    wildcard: true")
    else:
        if entry.accept:
            lines.append(f"    accept: {', '.join(entry.accept)}")
        if entry.reject:
            lines.append(f"    reject: {', '.join(entry.reject)}")
    return lines
