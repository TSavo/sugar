from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment


_CONTEXT_RECEIVERS = ("ctx", "source", "temporal")


@dataclass(frozen=True)
class GetattrDefaultContextSite:
    path: str
    line: int
    receiver: str
    field: str
    observed: str
    fix: str


@dataclass(frozen=True)
class GetattrDefaultContextReport:
    sites: tuple[GetattrDefaultContextSite, ...]

    @property
    def r(self) -> dict[str, int]:
        values = {receiver: 0 for receiver in _CONTEXT_RECEIVERS}
        for site in self.sites:
            values[site.receiver] += 1
        values["total"] = len(self.sites)
        return values

    @property
    def is_zero(self) -> bool:
        return not self.sites


def collect_getattr_default_context_frontier(root: Path) -> GetattrDefaultContextReport:
    kit_src = _kit_src(root)
    sites: list[GetattrDefaultContextSite] = []
    for path in sorted(kit_src.rglob("*.py")):
        rel = path.relative_to(kit_src).as_posix()
        source = path.read_text(encoding="utf-8")
        root_fragment = SourceFragment.from_source(source, rel)
        for fragment in root_fragment.walk():
            if not _is_getattr_default(fragment):
                continue
            args = fragment.call_args()
            receiver = args[0]
            if receiver.observed != "Name":
                continue
            receiver_name = receiver.name_id()
            if receiver_name not in _CONTEXT_RECEIVERS:
                continue
            field = _field_name(args[1], source)
            sites.append(
                GetattrDefaultContextSite(
                    path=rel,
                    line=fragment.line,
                    receiver=receiver_name,
                    field=field,
                    observed=fragment.source_text(source) or "<unknown getattr>",
                    fix=_fix(receiver_name, field),
                )
            )
    return GetattrDefaultContextReport(sites=tuple(sites))


def render_text(report: GetattrDefaultContextReport) -> str:
    lines = ["python context getattr-default frontier audit", "R:"]
    for receiver in _CONTEXT_RECEIVERS:
        lines.append(f"  {receiver}: {report.r[receiver]}")
    lines.append(f"  total: {report.r['total']}")
    lines.append(f"R(getattr-default-sites): {report.r['total']}")
    if report.sites:
        lines.append("context getattr-default sites:")
        for site in report.sites:
            lines.append(
                f"  - {site.path}:{site.line} {site.observed} "
                f"receiver={site.receiver} field={site.field} fix={site.fix}"
            )
    return "\n".join(lines) + "\n"


def _kit_src(root: Path) -> Path:
    candidates = (
        root / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "src/sugar_lift_py_tests",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _is_getattr_default(fragment: SourceFragment) -> bool:
    if fragment.observed != "Call":
        return False
    func = fragment.call_func()
    return (
        func.observed == "Name"
        and func.name_id() == "getattr"
        and fragment.call_arg_count() >= 3
    )


def _field_name(fragment: SourceFragment, source: str) -> str:
    if fragment.observed == "PrimitiveLiteral":
        value = fragment.literal_value()
        if isinstance(value, str):
            return value
    return fragment.source_text(source) or "<dynamic field>"


def _fix(receiver: str, field: str) -> str:
    return (
        f"replace with {receiver}.{field}; declare {field} on the owning context "
        "with an explicit default, or raise before this access if absence is a bug"
    )
