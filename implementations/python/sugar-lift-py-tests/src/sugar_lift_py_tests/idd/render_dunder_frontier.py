from __future__ import annotations

from .dunder_frontier_report import DunderFrontierReport


def render_text(report: DunderFrontierReport) -> str:
    lines = ["python dunder frontier audit", "R:"]
    for axis, value in report.r.values.items():
        lines.append(f"  {axis}: {value}")
    lines.append(f"  total: {report.r.total}")
    if report.missing_slots:
        lines.append("missing dunder slots:")
        for slot in report.missing_slots:
            lines.append(f"  - {slot.axis} {slot.name}")
            lines.append(f"    fix: {slot.fix}")
    if report.owned_slots:
        lines.append("owned dunder slots:")
        for slot in report.owned_slots:
            lines.append(f"  - {slot.axis} {slot.name}: {slot.owner}")
    return "\n".join(lines) + "\n"
