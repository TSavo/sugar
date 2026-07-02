from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment

from .gap_swallow_vector import GapSwallowReport, GapSwallowSite

_LOUD_BASES = {"FactoryGap", "RuntimeError", "Exception"}
_REDUCE_ADJACENT = {"TypeError", "ValueError", "AttributeError", "KeyError"}
_SANCTIONED_RECORDERS = {
    "record_gap",
    "gap_record",
    "append",
    "_send",
    "_record_dig_refusal",
    "_panic_no_sugar",
    "_truthy_degraded_reason",
    "_truthy_type_degraded_reason",
}
_REDUCTION_CALLS = {
    "reduce",
    "build_body",
    "_lift_literal_via_factory",
    "factory_steps",
    "constraint_formulas",
    "constraint_formula_steps",
    "getsource",
    "getsourcefile",
}


def collect_gap_swallow_frontier(root: str | Path) -> GapSwallowReport:
    kit_src = _kit_src(Path(root))
    offenders: list[GapSwallowSite] = []
    for path in sorted(kit_src.rglob("*.py")):
        rel = path.relative_to(kit_src).as_posix()
        if _excluded(rel):
            continue
        root_fragment = SourceFragment.from_source(path.read_text(encoding="utf-8"), rel)
        for fragment in [root_fragment, *root_fragment.walk()]:
            if fragment.observed not in {"Try", "TryStar"}:
                continue
            reduction_adjacent = _try_body_touches_reduction(fragment)
            for handler in fragment.try_handlers():
                names = _names_in_type(handler)
                loud = bool(names & _LOUD_BASES) or names == {"<bare>"}
                adjacent = bool(names & _REDUCE_ADJACENT) and reduction_adjacent
                if not (loud or adjacent):
                    continue
                if _handler_reraises_all_paths(handler):
                    continue
                if _handler_records_the_gap(handler):
                    continue
                offenders.append(
                    GapSwallowSite(
                        file=rel,
                        line=handler.line,
                        caught=_caught_source(handler),
                        disposition=_disposition(handler),
                    )
                )
    return GapSwallowReport(
        offenders=tuple(sorted(offenders, key=lambda site: (site.file, site.line)))
    )


def _kit_src(root: Path) -> Path:
    candidates = (
        root,
        root / "src/sugar_lift_py_tests",
        root / "sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "python/sugar-lift-py-tests/src/sugar_lift_py_tests",
    )
    for candidate in candidates:
        if candidate.name == "sugar_lift_py_tests" and candidate.exists():
            return candidate
    for candidate in candidates:
        if candidate.exists():
            kit = candidate / "sugar_lift_py_tests"
            if kit.exists():
                return kit
    return candidates[1]


def _excluded(rel: str) -> bool:
    return (
        rel.startswith("tests/")
        or rel.startswith("idd/")
        or "__pycache__" in rel
    )


def _names_in_type(handler: SourceFragment) -> set[str]:
    names = handler.except_handler_type_names()
    if names is None:
        return {"<bare>"}
    return {name.rsplit(".", 1)[-1] for name in names}


def _caught_source(handler: SourceFragment) -> str:
    names = handler.except_handler_type_names()
    if names is None:
        return "<bare>"
    if len(names) == 1:
        return names[0].rsplit(".", 1)[-1]
    return "(" + ", ".join(name.rsplit(".", 1)[-1] for name in names) + ")"


def _try_body_touches_reduction(try_fragment: SourceFragment) -> bool:
    for fragment in try_fragment.try_body().walk():
        if fragment.observed == "Call" and _call_name(fragment) in _REDUCTION_CALLS:
            return True
    return False


def _handler_reraises_all_paths(handler: SourceFragment) -> bool:
    statements = handler.except_handler_body().statements()
    return any(stmt.observed == "Raise" for stmt in statements) and all(
        stmt.observed not in {"Return", "Continue", "Break", "Pass"}
        for stmt in statements
    )


def _handler_records_the_gap(handler: SourceFragment) -> bool:
    gap_name = handler.except_handler_name()
    if gap_name is None:
        return False
    for fragment in handler.walk():
        if (
            fragment.observed == "Call"
            and _call_name(fragment) in _SANCTIONED_RECORDERS
            and _call_references_name(fragment, gap_name)
        ):
            return True
    return False


def _call_name(call: SourceFragment) -> str:
    return call.call_target_name() or ""


def _call_references_name(call: SourceFragment, name: str) -> bool:
    return any(
        fragment.observed == "Name" and fragment.name_id() == name
        for fragment in call.walk()
    )


def _disposition(handler: SourceFragment) -> str:
    for stmt in handler.except_handler_body().statements():
        if stmt.observed == "Return":
            return "returns-default"
        if stmt.observed == "Continue":
            return "continues"
        if stmt.observed == "Pass":
            return "passes"
    return "passes"
