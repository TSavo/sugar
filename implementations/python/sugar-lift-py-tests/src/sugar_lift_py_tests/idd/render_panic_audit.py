from __future__ import annotations

from .panic_audit_report import PanicAuditReport


def render_text(report: PanicAuditReport) -> str:
    lines = ["python numpy/pandas lift panic audit", "R:"]
    for axis, value in report.r.values.items():
        lines.append(f"  {axis}: {value}")
    if report.diagnostics:
        lines.append("diagnostics:")
        for diagnostic in report.diagnostics:
            lines.append(f"  - {diagnostic}")
    if report.records:
        lines.append("construction panics:")
        for record in report.records:
            lines.append(f"  - {record.target} {record.kind}: {record.message}")
            lines.append(f"    fix: {record.fix}")
    return "\n".join(lines) + "\n"
