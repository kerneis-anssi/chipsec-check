"""Report formatting: produce a human-readable table + summary counts."""

from __future__ import annotations

from typing import IO, List, Sequence

from uefi_policy.model import Result, Status

_ORDER = [Status.VIOLATION, Status.UNKNOWN_OPTION, Status.UNKNOWN_VALUE, Status.OK, Status.IGNORED]


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
        path = _truncate(result.option.path, 50)
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
