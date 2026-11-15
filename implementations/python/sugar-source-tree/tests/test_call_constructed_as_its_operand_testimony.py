"""A call that constructs as its operand presents its operand's sugar.

``typing.cast(typ, val)`` returns ``val``, so the call constructs as ``val``'s
sugar (``Call._construct_call_sugar``).  Where ``val`` is a source call, the
sugar presented at the ``cast`` call is the inner call's: sited there, naming
that call's occurrence.  The testimony reporter asked it the identity terms of
the ``cast`` call and refused it by ``call-occurrence-mismatch`` (pandas board,
CI run 43667269574: ``io/_util.py`` 235:15,
``cast("pd.Index | None", _maybe_convert_string_to_object(index))``).

Truthful twin: the cast call testifies, as its operand's sugar.  Lying twin: a
sugar sited at a call that names another call's occurrence is still refused by
``call-occurrence-mismatch``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, LanguageCallee
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
    return calls['cast("int", helper(value))'], calls["helper(value)"], reporter


def test_a_cast_over_a_source_call_testifies_as_its_operand(tmp_path) -> None:
    outer, inner, reporter = _cast_over_a_source_call(tmp_path)
    assert outer.language_callee() is LanguageCallee.TYPING_CAST
    operand_sugar = inner.sugar()

    # Node.sugar presents the operand's sugar at the cast call.
    sugar = outer.sugar()

    assert sugar.call_occurrence == operand_sugar.call_occurrence
    assert sugar.call_occurrence != outer.source_occurrence()
    assert reporter.testimony_for(outer) is not None


def test_a_sugar_sited_at_a_call_naming_another_occurrence_is_refused(
    tmp_path,
) -> None:
    outer, inner, reporter = _cast_over_a_source_call(tmp_path)
    lying = replace(inner.sugar(), call_occurrence=outer.source_occurrence())

    with pytest.raises(
        ConstructedValueTestimonyNotWritten,
        match="call-occurrence-mismatch",
    ):
        reporter.present_construction(inner, lying)
