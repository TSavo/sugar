"""Authenticated ``tuple(comprehension)`` coordinate construction teeth."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import (
    ComprehensionValue,
    TermValue,
    TupleCoordinateValue,
)
from sugar_lift_py_tests.ir import _term_content_cid, ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.nodes import Call, GeneratorExp, Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _ValueSugar(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _tree(tmp_path: Path, name: str, source: str) -> SourceFile:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return SourceFile.from_path(path)


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
    generator = next(node for node in tree.nodes() if isinstance(node, GeneratorExp))
    subscript = next(node for node in tree.nodes() if isinstance(node, Subscript))
    return call, generator, subscript


def _value(outcome):
    assert isinstance(outcome, Complete), outcome
    return outcome.value


def _authenticated_tuple(generator, call, ctx):
    source = _value(generator.sugar().desugar(ctx))
    assert isinstance(source, ComprehensionValue)
    assert source.finite_elements is None
    result = CallSiteSugar(
        "tuple", (_ValueSugar(source),), call.fragment
    ).desugar(ctx)
    return source, _value(result)


def test_builtin_tuple_unknown_comprehension_and_slice_keep_exact_coordinates(
    tmp_path: Path,
) -> None:
    tree = _tree(
        tmp_path,
        "truth.py",
        "result = tuple(item for item in unknown)[1:]\n",
    )
    call, generator, subscript = _nodes(tree)
    ctx = ReduceContext.root(owner="tuple-coordinate-truth")
    source, constructed = _authenticated_tuple(generator, call, ctx)

    assert isinstance(constructed, TupleCoordinateValue)
    assert constructed.source is source
    assert constructed.use_site == _coordinate(call)
    assert constructed.term == ctor("call:tuple", [source.term], symbol_kind="builtin")
    assert constructed.witness.operation == "python.tuple.construct"
    assert constructed.witness.operand_cids == (_term_content_cid(source.term),)
    assert constructed.witness.result_cid == _term_content_cid(constructed.term)
    assert not hasattr(constructed, "finite_elements")

    index = _value(subscript.sugar().index.desugar(ctx))
    sliced = _value(constructed.subscript(index, subscript.fragment))
    assert isinstance(sliced, TupleCoordinateValue)
    assert sliced.source is constructed
    assert sliced.index == index
    assert sliced.use_site == _coordinate(subscript)
    assert sliced.witness.operation == "python.tuple.slice"
    assert sliced.witness.operand_cids == (
        _term_content_cid(constructed.term),
        _term_content_cid(index.to_term(owner="test")),
    )
    assert sliced.witness.result_cid == _term_content_cid(sliced.term)
    with pytest.raises(SugarNotWritten):
        sliced.length(subscript.fragment)


def test_shadowed_and_foreign_tuple_producers_cannot_mint_coordinate(
    tmp_path: Path,
) -> None:
    truth = _tree(tmp_path, "truth.py", "result = tuple(x for x in xs)[1:]\n")
    foreign = _tree(tmp_path, "foreign.py", "result = tuple(x for x in xs)[1:]\n")
    truth_call, truth_generator, _ = _nodes(truth)
    foreign_call, _, _ = _nodes(foreign)
    ctx = ReduceContext.root(owner="tuple-coordinate-lies")
    source = _value(truth_generator.sugar().desugar(ctx))

    shadowed = ctx.with_temporal(ctx.temporal.bind_value("tuple", TermValue(7)))
    shadowed_result = _value(
        CallSiteSugar("tuple", (_ValueSugar(source),), truth_call.fragment).desugar(
            shadowed
        )
    )
    assert not isinstance(shadowed_result, TupleCoordinateValue)

    foreign_result = _value(
        CallSiteSugar("tuple", (_ValueSugar(source),), foreign_call.fragment).desugar(ctx)
    )
    assert not isinstance(foreign_result, TupleCoordinateValue)


def test_tuple_coordinate_refuses_reminted_operand_result_and_scalar_index(
    tmp_path: Path,
) -> None:
    tree = _tree(tmp_path, "truth.py", "result = tuple(x for x in xs)[1:]\n")
    call, generator, subscript = _nodes(tree)
    ctx = ReduceContext.root(owner="tuple-coordinate-remint")
    source, constructed = _authenticated_tuple(generator, call, ctx)
    index = _value(subscript.sugar().index.desugar(ctx))
    sliced = _value(constructed.subscript(index, subscript.fragment))
    foreign_source_cid = "blake3-512:" + "f" * 128
    foreign_same_span = replace(
        constructed.use_site, source_cid=foreign_source_cid
    )

    with pytest.raises(ValueError, match="tuple coordinate source/use testimony"):
        replace(constructed, use_site=foreign_same_span)
    with pytest.raises(ValueError, match="closed semantic operation witness"):
        replace(constructed, source=ComprehensionValue(make_var("foreign")))
    with pytest.raises(ValueError, match="closed semantic operation witness"):
        replace(
            constructed,
            witness=replace(
                constructed.witness, operation="python.set.construct"
            ),
        )
    with pytest.raises(ValueError, match="closed semantic operation witness"):
        replace(
            constructed,
            witness=replace(
                constructed.witness,
                operand_cids=(_term_content_cid(make_var("reminted")),),
            ),
        )
    with pytest.raises(ValueError, match="closed semantic operation witness"):
        replace(
            constructed,
            witness=replace(
                constructed.witness,
                result_cid=_term_content_cid(ctor("call:tuple", [source.term])),
            ),
        )
    with pytest.raises(ValueError, match="tuple coordinate source/use testimony"):
        replace(sliced, use_site=foreign_same_span)
    with pytest.raises(ValueError, match="closed semantic operation witness"):
        replace(sliced, index=TermValue(0))
    with pytest.raises(SugarNotWritten):
        constructed.subscript(TermValue(0), subscript.fragment)
