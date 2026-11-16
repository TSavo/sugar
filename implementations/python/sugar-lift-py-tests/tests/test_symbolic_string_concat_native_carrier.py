"""Symbolic + str concat must not SNW at binary_operation_exception_floor.

Recensus materialize of pandas files (e.g. io/json/_json.py) force-floors
transitive stdlib (enum.py). Bare NameSugar desugar of a formal yields
``SymbolicValue`` without ``formal_coordinate``; ``cls_name + '.'`` then raised
``SugarNotWritten(owner=binary_operation_exception_floor)`` at enum.py:75:16
and aborted SourceFile open with functionsTotal=0 before any function walk.

A SymbolicValue + StringValue, and the StringValue + SymbolicValue reverse,
take the one undecided binary law (two faces), which is also no SNW, whether
or not the symbolic is a parameter: no carrier is minted (#7757, audit row
NEW-1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_source_tree.nodes import BinOp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _tiny_binop_site():
    """Minimal fragment — NativeOperationExitCarrier.mint needs line_col_span."""
    from sugar_lift_python_source.canonical import blake3_512_of

    src = "def f(cls_name):\n    return cls_name + '.'\n"
    source = SourceFile(
        (src, "tiny_concat.py", blake3_512_of(src.encode("utf-8"))),
    )
    return next(node for node in source.nodes() if isinstance(node, BinOp)).fragment


def test_symbolic_plus_string_is_the_undecided_binary_law() -> None:
    """A formal-less ``symbolic + str`` has no coordinate a caller answers, so
    it is not deferred: it is the one undecided binary law's two faces, never
    a carrier that waits on no one and holds every face beside it (#7757:
    ``df[start : end[:-4] + "1:00"]`` lost its subscript halts that way)."""
    from sugar_lift_py_tests.outcome.exit_set import Halted

    site = _tiny_binop_site()
    left = SymbolicValue(make_var("cls_name"))
    right = StringValue(".")
    assert left.formal_coordinate is None
    outcome = left.add(right, site, None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [face.effect.producer_node_owner for face in halts] == [
        "UndecidedBinary:+"
    ]


def test_string_plus_symbolic_is_the_undecided_binary_law() -> None:
    """The reverse: a formal-less ``str + symbolic`` is the same law, never a
    carrier with no coordinate (#7757: ``df["s" + end[:-4]]``)."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    site = _tiny_binop_site()
    left = StringValue(".")
    right = SymbolicValue(make_var("cls_name"))
    assert right.formal_coordinate is None
    outcome = left.add(right, site, None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert any(isinstance(face, Completed) for face in outcome.exits)
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [face.effect.producer_node_owner for face in halts] == [
        "UndecidedBinary:+"
    ]


def _formal(site, name: str):
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import PrimitiveSort

    span = site.line_col_span
    locus = SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=locus.source_cid,
        owner_definition_locus=locus,
        declaration_locus=locus,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def test_string_plus_a_parameter_is_the_undecided_binary_law() -> None:
    """A parameter operand mints no carrier either (#7757, audit row NEW-1):
    the parameter's ``__radd__`` may answer after ``str.__add__``'s
    ``NotImplemented``, which no one dispatched method states, so ``"." + p``
    is the one undecided binary law's two faces, over the parameter's own
    term, whether or not its class is an input."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    site = _tiny_binop_site()
    formal = _formal(site, "cls_name")
    left = StringValue(".")
    right = SymbolicValue(make_var("cls_name"), formal)
    outcome = left.add(right, site, None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert "python:binary_op.completes" in repr(done.guard)
    assert done.value.term.name == "python:binary_result"
    assert done.value.term.args[2] == right.to_term(owner="test")
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [face.effect.producer_node_owner for face in halts] == [
        "UndecidedBinary:+"
    ]


def test_a_parameter_plus_string_is_the_undecided_binary_law() -> None:
    """The reverse, ``p + "."``: the same law, no carrier."""
    from sugar_lift_py_tests.outcome.exit_set import Halted

    site = _tiny_binop_site()
    formal = _formal(site, "cls_name")
    left = SymbolicValue(make_var("cls_name"), formal)
    outcome = left.add(StringValue("."), site, None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [face.effect.producer_node_owner for face in halts] == [
        "UndecidedBinary:+"
    ]


def test_symbolic_plus_int_is_the_undecided_binary_law() -> None:
    """Discrimination: a numeric undecided pair takes the undecided binary law
    (two faces, #7585), not the string-concat carrier door."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import Halted

    site = _tiny_binop_site()
    outcome = SymbolicValue(make_var("n")).add(TermValue(2), site, None)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [face.effect.producer_node_owner for face in halts] == [
        "UndecidedBinary:+"
    ]


def _enum_through_the_construction_door(tmp_path: Path):
    """The interpreter's own ``enum.py``, opened through the construction door.

    Its text is seated as ``enum.py`` in a workspace of its own, so the open
    carries a construction context without listing the whole stdlib directory
    as the workspace roster. Lines and columns are the live file's.
    """
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    enum_path = tmp_path / "enum.py"
    enum_path.write_text(
        Path(__import__("enum").__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return open_source_file_for_construction(
        enum_path,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def test_enum_py_line75_binop_desugar_does_not_snw(tmp_path: Path) -> None:
    """Live locus: enum._is_internal_class ``cls_name + '.' + getattr(...)``."""
    source = _enum_through_the_construction_door(tmp_path)
    binops = [
        node
        for node in source.nodes()
        if isinstance(node, BinOp)
        and node.line_col_span().start_line == 75
        and node.line_col_span().start_col == 16
    ]
    assert binops, "expected enum.py:75:16 BinOp"
    for node in binops:
        sugar = node.sugar()
        # Must not raise SugarNotWritten(binary_operation_exception_floor)
        outcome = sugar.desugar(None)
        assert outcome is not None
        # Two faces or a completion — never the old SNW abort.
        if isinstance(outcome, Exception):
            raise AssertionError(outcome)
        # Nested left is NameSugar/formal-less path: the undecided binary law.
        assert not isinstance(outcome, SugarNotWritten)


def test_enum_is_internal_class_function_sugar_still_constructs(tmp_path: Path) -> None:
    source = _enum_through_the_construction_door(tmp_path)
    function = next(fn for fn in source.functions() if fn.name == "_is_internal_class")
    sugar = function.sugar()
    outcome = sugar.desugar(None)
    assert outcome is not None
