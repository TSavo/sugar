from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment

from .temporal_dispatch_offender import TemporalDispatchOffender
from .temporal_dispatch_report import TemporalDispatchReport


def collect_temporal_dispatch_frontier(root: Path) -> TemporalDispatchReport:
    kit_src = _kit_src(root)
    offenders: list[TemporalDispatchOffender] = []
    for path in sorted(kit_src.rglob("*.py")):
        rel = path.relative_to(kit_src).as_posix()
        root_fragment = SourceFragment.from_source(path.read_text(encoding="utf-8"), rel)
        in_temporal_package = rel.startswith("temporal/")
        in_context_package = rel.startswith("context/")
        for fragment in root_fragment.walk():
            if not in_temporal_package and _is_bind_value_call(fragment):
                offenders.append(
                    _offender(
                        "direct_temporal_bindings",
                        rel,
                        fragment.line,
                        ".bind_value(...)",
                        "route temporal binding through temporal dispatch floor",
                    )
                )
            if not in_temporal_package and _is_temporal_replace_call(fragment):
                offenders.append(
                    _offender(
                        "direct_temporal_replacements",
                        rel,
                        fragment.line,
                        "replace(..., temporal=...)",
                        "route temporal context replacement through temporal dispatch floor",
                    )
                )
            if _is_temporal_rewrite_switch(fragment):
                offenders.append(
                    _offender(
                        "temporal_rewrite_switches",
                        rel,
                        fragment.line,
                        "TemporalContext.apply_step",
                        "route temporal rewrite through temporal dispatch floor",
                    )
                )
            if (
                not in_temporal_package
                and not in_context_package
                and _is_direct_context_minting(fragment)
            ):
                offenders.append(
                    _offender(
                        "direct_context_minting",
                        rel,
                        fragment.line,
                        "ReduceContext(temporal=...)",
                        "mint reduce contexts through ReduceContext.root/derived",
                    )
                )
    return TemporalDispatchReport(offenders=offenders)


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


def _is_bind_value_call(fragment: SourceFragment) -> bool:
    if fragment.observed != "Call":
        return False
    func = fragment.call_func()
    return func.observed == "Attribute" and func.attr_name() == "bind_value"


def _is_temporal_replace_call(fragment: SourceFragment) -> bool:
    if fragment.observed != "Call":
        return False
    func = fragment.call_func()
    return (
        func.observed == "Name"
        and func.name_id() == "replace"
        and any(
            keyword.keyword_arg_name() == "temporal"
            for keyword in fragment.call_keywords()
        )
    )


def _is_temporal_rewrite_switch(fragment: SourceFragment) -> bool:
    return fragment.observed == "FunctionDef" and fragment.function_name() == "apply_step"


def _is_direct_context_minting(fragment: SourceFragment) -> bool:
    if fragment.observed != "Call":
        return False
    func = fragment.call_func()
    if func.observed == "Attribute":
        name = func.attr_name()
    elif func.observed == "Name":
        name = func.name_id()
    else:
        name = ""
    return name == "ReduceContext" and any(
        keyword.keyword_arg_name() == "temporal"
        for keyword in fragment.call_keywords()
    )


def _offender(
    kind: str,
    path: str,
    line: int,
    observed: str,
    fix: str,
) -> TemporalDispatchOffender:
    return TemporalDispatchOffender(
        kind=kind,
        path=path,
        line=line,
        observed=observed,
        fix=fix,
    )
