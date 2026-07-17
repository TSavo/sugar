from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment

from .gap_swallow_vector import GapSwallowReport, GapSwallowSite

# FactoryPanic is BaseException on purpose (#4203): a normal `except Exception`
# cannot hold it. The auditor must still see bare `except FactoryPanic: pass`
# as a silent continue past a construction gap.
_LOUD_BASES = {"FactoryGap", "FactoryPanic", "RuntimeError", "Exception"}
_REDUCE_ADJACENT = {"TypeError", "ValueError", "AttributeError", "KeyError"}
_SANCTIONED_RECORDERS = {
    "record_gap",
    "gap_record",
    "append",
    "_send",
    "_record_dig_refusal",
    "_panic_no_sugar",
    "factory_panic",
    "factory_panic_gap",
    "_truthy_degraded_reason",
    "_truthy_type_degraded_reason",
}
# Process-terminal converters: calling these IS the loud break, not a swallow.
_LOUD_TERMINALS = {"factory_panic", "factory_panic_gap", "_panic_no_sugar"}
# Explicit #4203 recovery sinks. Continuing past FactoryPanic is legal only when
# the handler first re-raises if the sink is absent.
_RECOVERY_SINK_NAMES = {
    "recovered_panics",
    "recover_panics",
    "recovery_allowed",
    "hold_seed_panics",
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
    "force_floor",
}


def collect_gap_swallow_frontier(root: str | Path) -> GapSwallowReport:
    kit_src = _kit_src(Path(root))
    offenders: list[GapSwallowSite] = []
    for path in sorted(kit_src.rglob("*.py")):
        rel = path.relative_to(kit_src).as_posix()
        if _excluded(rel):
            continue
        root_fragment = SourceFragment.from_source(
            path.read_text(encoding="utf-8"), rel
        )
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
                if _handler_ends_in_loud_terminal(handler):
                    continue
                if _handler_is_recovery_gated(handler):
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
    return rel.startswith("tests/") or rel.startswith("idd/") or "__pycache__" in rel


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


def _handler_ends_in_loud_terminal(handler: SourceFragment) -> bool:
    """factory_panic(...) is process-terminal; treat it as a re-raise."""
    statements = handler.except_handler_body().statements()
    if not statements:
        return False
    if any(stmt.observed in {"Return", "Continue", "Break", "Pass"} for stmt in statements):
        return False
    return any(
        fragment.observed == "Call" and _call_name(fragment) in _LOUD_TERMINALS
        for fragment in handler.walk()
    )


def _handler_is_recovery_gated(handler: SourceFragment) -> bool:
    """#4203: continue/record only after an explicit recovery-sink absence check.

    Lawful shape:
        except FactoryPanic as panic:
            if recovered_panics is None:
                raise
            recovered_panics.append(...)
            continue
    """
    has_sink_guard = False
    for stmt in handler.except_handler_body().statements():
        if stmt.observed != "If":
            continue
        test = stmt.if_test()
        test_names = {
            fragment.name_id()
            for fragment in test.walk()
            if fragment.observed == "Name" and fragment.name_id() is not None
        }
        if not (test_names & _RECOVERY_SINK_NAMES):
            continue
        body = stmt.if_body()
        if any(item.observed == "Raise" for item in body):
            has_sink_guard = True
            break
    if not has_sink_guard:
        return False
    # After the guard, recovery may continue or record; bare pass is still illegal.
    disposition = _disposition(handler)
    if disposition == "passes" and not _handler_records_the_gap(handler):
        # Only allow pass when every path still raises (handled elsewhere).
        return _handler_reraises_all_paths(handler)
    return disposition in {"continues", "returns-default"} or _handler_records_the_gap(
        handler
    )


def _handler_records_the_gap(handler: SourceFragment) -> bool:
    gap_name = handler.except_handler_name()
    # Unnamed handlers cannot prove they recorded the gap.
    if gap_name is None:
        return False
    for fragment in handler.walk():
        if (
            fragment.observed == "Call"
            and _call_name(fragment) in _SANCTIONED_RECORDERS
            and _call_references_name(fragment, gap_name)
        ):
            return True
        if (
            fragment.observed == "Call"
            and _call_name(fragment) in _LOUD_TERMINALS
            and _handler_references_name(handler, gap_name)
        ):
            return True
    return _handler_returns_runtime_effect(handler) and _handler_references_name(
        handler, gap_name
    )


def _handler_returns_runtime_effect(handler: SourceFragment) -> bool:
    has_runtime_effect = any(
        fragment.observed == "Call" and _call_name(fragment) == "RuntimeEffect"
        for fragment in handler.walk()
    )
    if not has_runtime_effect:
        return False
    for statement in handler.except_handler_body().statements():
        if statement.observed != "Return":
            continue
        if any(
            fragment.observed == "Call" and _call_name(fragment) == "Incomplete"
            for fragment in statement.walk()
        ):
            return True
    return False


def _call_name(call: SourceFragment) -> str:
    return call.call_target_name() or ""


def _handler_references_name(handler: SourceFragment, name: str) -> bool:
    return any(
        fragment.observed == "Name" and fragment.name_id() == name
        for fragment in handler.walk()
    )


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
