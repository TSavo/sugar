from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.source_fragment import SourceFragment

from .factory_spine_offender import FactorySpineOffender
from .factory_spine_report import FactorySpineReport

_LITERAL_CALL_REPORT = "factory/literal_call_report.py"
_CALL_SUGAR = "sugar/call_sugar.py"


def collect_factory_spine_frontier(root: Path) -> FactorySpineReport:
    kit_src = _kit_src(root)
    literal_call_report = kit_src / _LITERAL_CALL_REPORT
    offenders: list[FactorySpineOffender] = []
    if literal_call_report.exists():
        source = literal_call_report.read_text(encoding="utf-8")
        lines = source.splitlines()
        root_fragment = SourceFragment.from_source(source, _LITERAL_CALL_REPORT)
        for fragment in root_fragment.walk():
            if fragment.observed not in {"FunctionDef", "AsyncFunctionDef"}:
                continue
            offenders.extend(_function_offenders(fragment, lines))
    call_sugar = kit_src / _CALL_SUGAR
    if call_sugar.exists():
        offenders.extend(
            _call_sugar_offenders(
                call_sugar.read_text(encoding="utf-8").splitlines()
            )
        )
    return FactorySpineReport(offenders=sorted(offenders, key=_sort_key))


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


def _function_offenders(
    fragment: SourceFragment, source_lines: list[str]
) -> list[FactorySpineOffender]:
    name = fragment.function_name()
    span = _function_lines(fragment, source_lines)
    offenders: list[FactorySpineOffender] = []
    offenders.extend(_block_of_callee_body_reduce_offenders(span))
    if name == "_lift_assert":
        offenders.extend(_assert_consumer_offenders(span))
    if name == "_ctx_with_prior_assignments":
        offenders.extend(_prior_assignment_replay_offenders(span))
    if name == "_construct_callsite":
        offenders.extend(_construct_callsite_offenders(span))
    if name == "_concrete_return_value":
        offenders.extend(_concrete_return_value_offenders(span))
    return offenders


def _function_lines(
    fragment: SourceFragment, source_lines: list[str]
) -> list[tuple[int, str]]:
    start = max(fragment.line, 1)
    end = max(fragment.end_line, start)
    return [
        (line_no, source_lines[line_no - 1])
        for line_no in range(start, min(end, len(source_lines)) + 1)
    ]


def _prior_assignment_replay_offenders(
    span: list[tuple[int, str]]
) -> list[FactorySpineOffender]:
    for line_no, text in span:
        if "build_body(" in text and ".reduce(" in text:
            return [
                _offender(
                    "prior_assignment_replays",
                    line_no,
                    "build_body(...).reduce(...) in _ctx_with_prior_assignments",
                    "reduce the enclosing block through BlockSugar and let bind_temporal own assignment replay",
                )
            ]
    return []


def _construct_callsite_offenders(
    span: list[tuple[int, str]]
) -> list[FactorySpineOffender]:
    offenders: list[FactorySpineOffender] = []
    projection_lines: list[int] = []
    for line_no, text in span:
        stripped = text.strip()
        if stripped.startswith("while worklist:"):
            offenders.append(
                _offender(
                    "callee_body_worklists",
                    line_no,
                    "while worklist",
                    "drive callee floors through force_floor + project_callsite_with",
                )
            )
        if "worklist.extend(sink)" in text:
            offenders.append(
                _offender(
                    "transitive_worklist_drains",
                    line_no,
                    "worklist.extend(sink)",
                    "let BridgeStrategy dig_sink carry transitive obligations",
                )
            )
        if "isinstance(result," in text and any(
            floor_name in text
            for floor_name in ("TermValue", "SymbolicValue", "CallSiteValue")
        ):
            projection_lines.append(line_no)
    if projection_lines:
        offenders.append(
            _offender(
                "projection_ladders",
                min(projection_lines),
                "isinstance ladder over floor values in _construct_callsite",
                "move callsite projection to project_callsite_with floor arms",
            )
        )
    return offenders


def _block_of_callee_body_reduce_offenders(
    span: list[tuple[int, str]]
) -> list[FactorySpineOffender]:
    return [
        _offender(
            "block_of_callee_body_reductions",
            line_no,
            "build_body(Block.of(callee.node.body), ...).reduce(...)",
            "reduce callee bodies through CallSiteValue.force_floor seated on the factory spine",
        )
        for line_no, text in span
        if "Block.of(callee.node.body)" in text
    ]


def _concrete_return_value_offenders(
    span: list[tuple[int, str]]
) -> list[FactorySpineOffender]:
    for line_no, text in span:
        if "isinstance(statements[0], ReturnValue)" in text:
            return [
                _offender(
                    "projection_ladders",
                    line_no,
                    "isinstance ladder over ReturnValue in _concrete_return_value",
                    "move concrete-return projection to project_callsite_with floor arms",
                )
            ]
    return []


def _assert_consumer_offenders(
    span: list[tuple[int, str]]
) -> list[FactorySpineOffender]:
    for line_no, text in span:
        if "_construct_callsite(" in text:
            return [
                _offender(
                    "mini_interpreter_consumers_not_reading_terms",
                    line_no,
                    "_lift_assert calls _construct_callsite instead of reading the factory term",
                    "build the callsite through the factory, demand force_floor, and project with project_callsite_with",
                )
            ]
    return []


def _call_sugar_offenders(source_lines: list[str]) -> list[FactorySpineOffender]:
    offenders: list[FactorySpineOffender] = []
    for line_no, text in enumerate(source_lines, start=1):
        compact = "".join(text.split())
        if "body=self.bodyifisinstance(self.body,SugarBody)elseNone" in compact:
            offenders.append(
                _offender(
                    "callsite_values_with_null_multistatement_body",
                    line_no,
                    "BridgeStrategy drops FunctionBodyUniverse bodies to None",
                    "carry the FunctionBodyUniverse into CallSiteValue and reduce it through BlockSugar in force_floor",
                    path=_CALL_SUGAR,
                )
            )
    return offenders


def _offender(
    kind: str,
    line: int,
    observed: str,
    fix: str,
    *,
    path: str = _LITERAL_CALL_REPORT,
) -> FactorySpineOffender:
    return FactorySpineOffender(
        kind=kind,
        path=path,
        line=line,
        observed=observed,
        fix=fix,
    )


def _sort_key(offender: FactorySpineOffender) -> tuple[str, int, str]:
    return (offender.path, offender.line, offender.kind)
