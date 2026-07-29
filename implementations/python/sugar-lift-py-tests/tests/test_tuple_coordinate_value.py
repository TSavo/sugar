"""Authenticated source ``tuple(comprehension)[slice]`` coordinate teeth."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    FloorValue,
    GuardedValue,
    TermValue,
    TupleCoordinateValue,
)
from sugar_lift_py_tests.ir import _term_content_cid, atomic, ctor, make_var
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
    use_site = call.fragment
    length = _value(constructed.length(use_site))
    assert isinstance(length, CallSiteValue)
    assert length.arg_values == (constructed,)
    assert length.site is use_site
    assert length.term == ctor(
        "call:len", (constructed.term,), symbol_kind="builtin"
    )


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
    use_site = subscript.fragment
    length = _value(sliced.length(use_site))
    assert isinstance(length, CallSiteValue)
    assert length.arg_values == (sliced,)
    assert length.site is use_site
    assert length.term == ctor("call:len", (sliced.term,), symbol_kind="builtin")


def test_tuple_coordinate_length_keeps_receiver_and_use_sites_distinct(
    tmp_path: Path,
) -> None:
    call, subscript = _nodes(_tree(tmp_path, "length-sites.py"))
    ctx = _context("tuple-coordinate-length-sites")
    receiver = _value(call.sugar().desugar(ctx))

    call_site = call.fragment
    subscript_site = subscript.fragment
    call_length = _value(receiver.length(call_site))
    subscript_length = _value(receiver.length(subscript_site))

    assert call_length.arg_values[0] is receiver
    assert subscript_length.arg_values[0] is receiver
    assert call_length.site is call_site
    assert subscript_length.site is subscript_site
    assert call_site is not subscript_site
    assert call_site.seal().cid != subscript_site.seal().cid
    foreign_occurrence = replace(
        receiver.call_occurrence, source_cid="blake3-512:" + "e" * 128
    )
    with pytest.raises(
        ValueError, match="tuple coordinate call occurrence does not authenticate source"
    ):
        replace(receiver, call_occurrence=foreign_occurrence)
    with pytest.raises(
        ValueError, match="tuple coordinate requires its private producer authority"
    ):
        TupleCoordinateValue(
            source=receiver.source,
            call_occurrence=receiver.call_occurrence,
            call_occurrence_cid=receiver.call_occurrence_cid,
            term=receiver.term,
            witness=receiver.witness,
            coordinate_cid=receiver.coordinate_cid,
        )


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


def test_guarded_tuple_slice_preserves_exact_occurrence_in_both_arms(
    tmp_path: Path,
) -> None:
    call, subscript = _nodes(_tree(tmp_path, "guarded-slice.py"))
    ctx = _context("guarded-tuple-slice")
    receiver = _value(call.sugar().desugar(ctx))
    index = _value(subscript.sugar().index.desugar(ctx))
    occurrence = _coordinate(subscript)
    guard = atomic("tuple_slice_guard", ())

    outcome = GuardedValue(guard, receiver, receiver).subscript_with_occurrence(
        index, subscript.fragment, occurrence
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GuardedValue)
    assert outcome.value.guard == guard
    assert outcome.value.when_true.use_occurrence is occurrence
    assert outcome.value.when_false.use_occurrence is occurrence
    assert outcome.value.when_true.coordinate_cid == outcome.value.when_false.coordinate_cid


def test_guarded_subscript_preserves_foreign_occurrence_refusal(
    tmp_path: Path,
) -> None:
    call, subscript = _nodes(_tree(tmp_path, "guarded-foreign.py"))
    ctx = _context("guarded-tuple-slice-foreign")
    receiver = _value(call.sugar().desugar(ctx))
    index = _value(subscript.sugar().index.desugar(ctx))
    foreign_occurrence = replace(
        _coordinate(subscript), source_cid="blake3-512:" + "d" * 128
    )
    guarded = GuardedValue(
        atomic("foreign_slice_guard", ()), receiver, receiver
    )

    with pytest.raises(SugarNotWritten) as raised:
        guarded.subscript_with_occurrence(
            index, subscript.fragment, foreign_occurrence
        )

    assert raised.value.owner == "TupleCoordinateValue.subscript"
    assert raised.value.observed == "slice use occurrence outside tuple source"
    assert raised.value.requested == "same-source authenticated slice occurrence"
