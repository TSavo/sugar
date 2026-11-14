"""Symbolic + str concat must not SNW at binary_operation_exception_floor.

Recensus materialize of pandas files (e.g. io/json/_json.py) force-floors
transitive stdlib (enum.py). Bare NameSugar desugar of a formal yields
``SymbolicValue`` without ``formal_coordinate``; ``cls_name + '.'`` then raised
``SugarNotWritten(owner=binary_operation_exception_floor)`` at enum.py:75:16
and aborted SourceFile open with functionsTotal=0 before any function walk.

Formal-seated formals already mint NativeOperationExitCarrierV1. This law
extends the same carrier to formal-less SymbolicValue + StringValue (and the
str + symbolic reverse) so materialize can complete and enumerate functions.
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


def test_symbolic_plus_string_mints_native_operation_carrier() -> None:
    site = _tiny_binop_site()
    left = SymbolicValue(make_var("cls_name"))
    right = StringValue(".")
    assert left.formal_coordinate is None
    outcome = left.add(right, site)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "add"


def test_string_plus_symbolic_mints_native_operation_carrier() -> None:
    site = _tiny_binop_site()
    left = StringValue(".")
    right = SymbolicValue(make_var("cls_name"))
    outcome = left.add(right, site)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "add"


def test_symbolic_plus_int_is_the_undecided_binary_law() -> None:
    """Discrimination: a numeric undecided pair takes the undecided binary law
    (two faces, #7585), not the string-concat carrier door."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import Halted

    site = _tiny_binop_site()
    outcome = SymbolicValue(make_var("n")).add(TermValue(2), site)
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
        # Prefer carrier or Complete — never the old SNW abort.
        if isinstance(outcome, Exception):
            raise AssertionError(outcome)
        # Nested left is NameSugar/formal-less path; carrier or nested Complete.
        assert not isinstance(outcome, SugarNotWritten)


def test_enum_is_internal_class_function_sugar_still_constructs(tmp_path: Path) -> None:
    source = _enum_through_the_construction_door(tmp_path)
    function = next(fn for fn in source.functions() if fn.name == "_is_internal_class")
    sugar = function.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1) or outcome is not None
