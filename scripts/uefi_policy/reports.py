"""Report formatting: produce a human-readable table + summary counts."""

from __future__ import annotations

from typing import IO, List, Sequence

from uefi_policy.model import Result, Status

_ORDER = [Status.VIOLATION, Status.UNKNOWN_OPTION, Status.UNKNOWN_VALUE, Status.OK, Status.IGNORED]


def build_report(results: Sequence[Result]) -> str:
    lines: List[str] = []
    lines.append(f"{'OPTION':<50} {'CURRENT':<40} STATUS")
    lines.append("-" * 100)
    by_status: dict = {}
    for result in results:
        status = result.primary_status
        current = (result.option.current_value or "").replace("\n", "\\n")
        if len(current) > 38:
            current = current[:38] + "..."
        if len(result.option.path) > 49:
            path = result.option.path[:49] + "..."
        else:
            path = result.option.path
        lines.append(f"{path:<50} {current:<40} {status.value}")
        by_status[status] = by_status.get(status, 0) + 1

    lines.append("")
    lines.append("Summary:")
    for status in _ORDER:
        if status in by_status:
            lines.append(f"  {status.value:<16} {by_status[status]}")
    return "\n".join(lines)


def write_report(report: str, stream: IO[str]) -> None:
    stream.write(report + "\n")
