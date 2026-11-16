"""A call that constructs as its operand presents its operand's sugar.

``typing.cast(typ, val)`` returns ``val``, so the call constructs as ``val``'s
sugar (``Call._construct_call_sugar``).  Where ``val`` is a source call, the
sugar presented at the ``cast`` call is the inner call's: sited there, naming
that call's occurrence.  The testimony reporter asked it the identity terms of
the ``cast`` call and refused it by ``call-occurrence-mismatch`` (pandas board,
CI run 43667269574: ``io/_util.py`` 235:15,
``cast("pd.Index | None", _maybe_convert_string_to_object(index))``).

Since #8603 the ``cast`` call builds its own sugar (``TypingCastSugar``: its
type operand evaluated and discarded, then ``val``), and a call of a same-file
``def`` is that function value's application (#8958), which names no
definition occurrence; so neither presents the operand's call-site sugar at
the ``cast`` call any more.

Truthful twin: the cast call testifies, as its own sugar over its operand's.
Lying twin: a call-site sugar that names its definition occurrence (the one
producer is the recursion seat, ``Call._recursion_seat_call``) and another
call's occurrence is still refused by ``call-occurrence-mismatch``.
"""

from __future__ import annotations


import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef, LanguageCallee
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter


def _cast_over_a_source_call(tmp_path):
    """``cast("int", helper(value))`` and its operand call, under one
    testimony roll."""
    path = tmp_path / "casted.py"
    path.write_text(
        "from typing import cast\n\n\n"
        "def helper(value):\n"
        "    return value\n\n\n"
        "def caller(value):\n"
        '    return cast("int", helper(value))\n'
    )
    collector = CollectingReporter()
    source = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=collector,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    calls = {node.segment(): node for node in root.walk() if isinstance(node, Call)}
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    return (
        calls['cast("int", helper(value))'],
        calls["helper(value)"],
        reporter,
        definition,
    )


def test_a_cast_over_a_source_call_testifies_as_its_operand(tmp_path) -> None:
    from sugar_lift_py_tests.sugar.typing_cast_sugar import TypingCastSugar

    outer, inner, reporter, _definition = _cast_over_a_source_call(tmp_path)
    assert outer.language_callee() is LanguageCallee.TYPING_CAST
    operand_sugar = inner.sugar()

    # Node.sugar presents the cast's own sugar, over its operand's.
    sugar = outer.sugar()

    assert isinstance(sugar, TypingCastSugar)
    assert type(sugar.value) is type(operand_sugar)
    assert reporter.testimony_for(outer) is not None


def test_a_sugar_sited_at_a_call_naming_another_occurrence_is_refused(
    tmp_path,
) -> None:
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

    outer, inner, reporter, definition = _cast_over_a_source_call(tmp_path)
    # The seated call-site sugar (``Call._recursion_seat_call``'s shape) at
    # the inner call, naming the cast call's occurrence instead of its own.
    lying = CallSiteSugar(
        target_name=inner.func.id,
        args=(),
        site=inner.fragment,
        call_occurrence=outer.source_occurrence(),
        expected_definition_ref=definition,
    )

    with pytest.raises(
        ConstructedValueTestimonyNotWritten,
        match="call-occurrence-mismatch",
    ):
        reporter.present_construction(inner, lying)
