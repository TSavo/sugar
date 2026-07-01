from __future__ import annotations

from .temporal_dispatch_report import TemporalDispatchReport


def render_text(report: TemporalDispatchReport) -> str:
    lines = ["python temporal dispatch frontier audit", "R:"]
    for axis, value in report.r.values.items():
        lines.append(f"  {axis}: {value}")
    lines.append(f"  total: {report.r.total}")
    if report.offenders:
        lines.append("temporal dispatch side doors:")
        for offender in report.offenders:
            lines.append(
                f"  - {offender.kind} {offender.path}:{offender.line} "
                f"{offender.observed}"
            )
            lines.append(f"    fix: {offender.fix}")
    return "\n".join(lines) + "\n"
