"""RED option: exact ClassDef chained fields from CPython's ``re`` source."""

from __future__ import annotations

import importlib.util

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_source_tree.nodes import Assign, ClassDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _available_backends():
    cases = [pytest.param(None, id="canonical-default")]
    if importlib.util.find_spec("libcst") is not None:
        from sugar_source_tree.libcst_adapter import LibCSTBackend

        cases.append(pytest.param(LibCSTBackend(), id="libcst"))
    if importlib.util.find_spec("parso") is not None:
        from sugar_source_tree.parso_adapter import ParsoBackend

        cases.append(pytest.param(ParsoBackend(), id="parso"))
    if (
        importlib.util.find_spec("tree_sitter") is not None
        and importlib.util.find_spec("tree_sitter_python") is not None
    ):
        from sugar_source_tree.tree_sitter_python_adapter import (
            TreeSitterPythonBackend,
        )

        cases.append(
            pytest.param(TreeSitterPythonBackend(), id="tree-sitter-python")
        )
    return tuple(cases)


def _authenticated_re_source(backend=None) -> tuple[SourceFile, ClassDef]:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    assert graph.distribution_version == "cpython-312"
    assert module.source_seat == "re/__init__.py"
    assert module.source.splitlines()[145] == (
        "    IGNORECASE = I = _compiler.SRE_FLAG_IGNORECASE # ignore case"
    )
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid), backend=backend
    )
    regex_flag = next(
        node
        for node in source.nodes()
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    return source, regex_flag


def _line_assignment(class_node: ClassDef, line: int) -> Assign:
    return next(
        node
        for node in class_node.body
        if isinstance(node, Assign) and node.line_col_span().start_line == line
    )


@pytest.mark.parametrize("backend", _available_backends())
def test_re_regexflag_chained_names_retain_targets_and_one_evaluated_floor(
    backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, class_node = _authenticated_re_source(backend)
    assignment = _line_assignment(class_node, 146)

    assert tuple(target.id for target in assignment.targets) == ("IGNORECASE", "I")
    assert tuple(target.segment() for target in assignment.targets) == (
        "IGNORECASE",
        "I",
    )
    assert tuple(
        (
            target.line_col_span().start_line,
            target.line_col_span().start_col,
            target.line_col_span().end_line,
            target.line_col_span().end_col,
        )
        for target in assignment.targets
    ) == ((146, 4, 146, 14), (146, 17, 146, 18))

    exact_floor = TermValue(2)
    evaluations = 0

    def authenticated_attribute_floor(self, ctx=None):
        nonlocal evaluations
        span = self.site.node.line_col_span()
        if self.name.startswith("SRE_FLAG_") and 145 <= span.start_line <= 154:
            if span.start_line == 146 and self.name == "SRE_FLAG_IGNORECASE":
                evaluations += 1
                return Complete(exact_floor)
            return Complete(TermValue(span.start_line))
        return Complete(TermValue(span.start_line))

    monkeypatch.setattr(AttributeSugar, "desugar", authenticated_attribute_floor)

    sugar = class_node.sugar()
    fields = tuple(
        field for field in sugar.fields if field.name in {"IGNORECASE", "I"}
    )
    assert tuple(field.name for field in fields) == ("IGNORECASE", "I")
    assert fields[0].value_sugar is fields[1].value_sugar
    debug = next(field for field in sugar.fields if field.name == "DEBUG")
    assert fields[0].evaluation_group_cid == fields[1].evaluation_group_cid
    assert debug.evaluation_group_cid != fields[0].evaluation_group_cid
    assert tuple(
        (
            field.binding_target_occurrence.start_line,
            field.binding_target_occurrence.start_col,
            field.binding_target_occurrence.end_line,
            field.binding_target_occurrence.end_col,
        )
        for field in fields
    ) == ((146, 4, 146, 14), (146, 17, 146, 18))

    constructed = sugar.desugar().value
    values = tuple(
        field.value
        for field in constructed.class_fields
        if field.name in {"IGNORECASE", "I"}
    )
    assert evaluations == 1
    assert values == (exact_floor, exact_floor)
    assert values[0] is values[1]


def test_removing_class_chained_assign_arm_restores_exact_re_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, class_node = _authenticated_re_source()
    original = ClassDef._construct_sugar

    def legacy_single_name_only(self):
        chained = next(
            (
                item
                for item in self.body
                if isinstance(item, Assign) and len(item.targets) > 1
            ),
            None,
        )
        if chained is not None:
            raise SugarNotWritten(
                blame=chained.fragment,
                owner="ClassDef._construct_sugar",
                observed="unsupported class member Assign",
                requested="a total source-visible class member construction arm",
                fix="add the member's ordinary node Sugar arm or keep the class loud",
            )
        return original(self)

    monkeypatch.setattr(ClassDef, "_construct_sugar", legacy_single_name_only)

    with pytest.raises(SugarNotWritten) as excinfo:
        class_node.sugar()
    error = excinfo.value
    assert error.owner == "ClassDef._construct_sugar"
    assert error.observed == "unsupported class member Assign"
    assert error.blame.line_col_span == _line_assignment(
        class_node, 145
    ).line_col_span()
    assert error.blame.line_col_span.start_line == 145
    assert error.blame.line_col_span.start_col == 4


def test_class_chained_assignment_refuses_a_non_name_target() -> None:
    source = SourceFile(
        ("class Flags:\n    I = holder.IGNORECASE = 7\n", "lying.py", "cid")
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))

    with pytest.raises(SugarNotWritten, match="unsupported class member Assign"):
        class_node.sugar()
