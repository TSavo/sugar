from __future__ import annotations

from .factory_spine_report import FactorySpineReport


def render_text(report: FactorySpineReport) -> str:
    lines = ["python factory spine frontier audit", "R:"]
    for key, value in report.r.values.items():
        lines.append(f"  {key}: {value}")
    lines.append(f"  total: {report.r.total}")
    if report.offenders:
        lines.append("factory spine frontier offenders:")
        for offender in report.offenders:
            lines.append(
                f"  - {offender.kind} {offender.path}:{offender.line}: "
                f"{offender.observed} -> {offender.fix}"
            )
    return "\n".join(lines) + "\n"
