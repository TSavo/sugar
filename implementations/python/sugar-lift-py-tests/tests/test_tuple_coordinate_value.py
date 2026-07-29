"""Authenticated source ``tuple(comprehension)[slice]`` coordinate teeth."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import ComprehensionValue, TermValue, TupleCoordinateValue
from sugar_lift_py_tests.ir import _term_content_cid, ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import Call, Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_python_source.canonical import cid_of_json


def _tree(tmp_path: Path, name: str) -> SourceFile:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    path = tmp_path / name
    path.write_text(
        "result = tuple(item for item in unknown)[1:]\n", encoding="utf-8"
    )
    return SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _nodes(tree: SourceFile):
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    subscript = next(node for node in tree.nodes() if isinstance(node, Subscript))
    return call, subscript


def _value(outcome):
    assert isinstance(outcome, Complete), outcome
    return outcome.value


def _context(owner: str):
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    return ReduceContext.root(owner=owner).with_temporal(builtin_name_temporal())


def test_source_builtin_tuple_constructs_authenticated_coordinate(tmp_path: Path) -> None:
    call, _ = _nodes(_tree(tmp_path, "truth.py"))
    ctx = _context("tuple-coordinate-truth")

    constructed = _value(call.sugar().desugar(ctx))

    assert isinstance(constructed, TupleCoordinateValue)
    assert isinstance(constructed.source, ComprehensionValue)
    assert constructed.source.finite_elements is None
    assert constructed.call_occurrence == _coordinate(call)
    assert constructed.term == ctor(
        "python.tuple.construct",
        (constructed.source.term,),
        symbol_kind="coordinate",
    )
    assert constructed.witness.operation == "python.tuple.construct"
    assert constructed.witness.operand_cids == (
        _term_content_cid(constructed.source.term),
    )
    assert constructed.witness.result_cid == _term_content_cid(constructed.term)
    assert not hasattr(constructed, "finite_elements")
    with pytest.raises(SugarNotWritten):
        constructed.length(call.fragment)


def test_source_tuple_slice_extends_receiver_coordinate_and_occurrence(
    tmp_path: Path,
) -> None:
    call, subscript = _nodes(_tree(tmp_path, "slice.py"))
    ctx = _context("tuple-coordinate-slice")
    receiver = _value(call.sugar().desugar(ctx))
    index = _value(subscript.sugar().index.desugar(ctx))

    sliced = _value(subscript.sugar().desugar(ctx))

    assert isinstance(receiver, TupleCoordinateValue)
    assert isinstance(sliced, TupleCoordinateValue)
    assert sliced.source.coordinate_cid == receiver.coordinate_cid
    assert sliced.index == index
    assert sliced.use_occurrence == _coordinate(subscript)
    assert sliced.witness == receiver.witness
    expected_cid = cid_of_json(
        {
            "kind": "python-tuple-slice-coordinate",
            "schemaVersion": "1",
            "receiverCoordinateCid": receiver.coordinate_cid,
            "constructorWitnessCid": receiver.witness.witness_cid,
            "indexCid": _term_content_cid(index.to_term(owner="test")),
            "useOccurrence": _coordinate(subscript).wire(),
            "useOccurrenceCid": _coordinate(subscript).cid,
            "resultKind": "tuple",
            "resultTermCid": _term_content_cid(sliced.term),
        }
    )
    assert sliced.coordinate_cid == expected_cid
    assert not hasattr(sliced, "finite_elements")
    with pytest.raises(SugarNotWritten):
        sliced.length(subscript.fragment)


def test_shadowed_tuple_call_cannot_mint_tuple_coordinate(tmp_path: Path) -> None:
    call, _ = _nodes(_tree(tmp_path, "shadowed.py"))
    ctx = _context("tuple-coordinate-shadow")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("tuple", TermValue(7)))

    shadowed = _value(call.sugar().desugar(ctx))

    assert not isinstance(shadowed, TupleCoordinateValue)


def test_tuple_coordinate_rejects_all_reminted_testimony(tmp_path: Path) -> None:
    call, subscript = _nodes(_tree(tmp_path, "remint.py"))
    ctx = _context("tuple-coordinate-remint")
    constructed = _value(call.sugar().desugar(ctx))
    sliced = _value(subscript.sugar().desugar(ctx))
    foreign_occurrence = replace(
        constructed.call_occurrence, source_cid="blake3-512:" + "f" * 128
    )

    with pytest.raises(
        ValueError, match="tuple coordinate call occurrence does not authenticate source"
    ):
        replace(constructed, call_occurrence=foreign_occurrence)
    with pytest.raises(
        ValueError, match="closed semantic operation witness does not authenticate"
    ):
        replace(constructed, source=ComprehensionValue(make_var("reminted")))
    with pytest.raises(
        ValueError, match="closed semantic operation witness does not authenticate"
    ):
        replace(
            constructed,
            witness=replace(constructed.witness, operation="python.set.construct"),
        )
    with pytest.raises(
        ValueError, match="closed semantic operation witness does not authenticate"
    ):
        replace(
            constructed,
            witness=replace(
                constructed.witness,
                result_cid=_term_content_cid(ctor("reminted", ())),
            ),
        )
    with pytest.raises(
        ValueError,
        match="tuple slice coordinate does not authenticate receiver, index, and use occurrence",
    ):
        replace(sliced, index=TermValue(0))
    with pytest.raises(
        ValueError,
        match="tuple slice coordinate does not authenticate receiver, index, and use occurrence",
    ):
        replace(sliced, use_occurrence=foreign_occurrence)
    with pytest.raises(
        ValueError,
        match="tuple slice coordinate does not authenticate receiver, index, and use occurrence",
    ):
        replace(sliced, coordinate_cid=cid_of_json({"reminted": True}))
    with pytest.raises(SugarNotWritten):
        constructed.subscript(TermValue(0), subscript.fragment)
