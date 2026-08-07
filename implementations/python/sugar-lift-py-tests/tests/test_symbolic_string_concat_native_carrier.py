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


def test_symbolic_plus_int_still_refuses_undecided() -> None:
    """Discrimination: numeric undecided pair stays SNW (not string-concat door)."""
    site = _tiny_binop_site()
    with pytest.raises(SugarNotWritten) as raised:
        SymbolicValue(make_var("n")).add(TermValue(2), site)
    assert raised.value.owner == "binary_operation_exception_floor"


def test_enum_py_line75_binop_desugar_does_not_snw() -> None:
    """Live locus: enum._is_internal_class ``cls_name + '.' + getattr(...)``."""
    enum_path = Path(__import__("enum").__file__)
    source = SourceFile.from_path(
        enum_path,
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
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


def test_enum_is_internal_class_function_sugar_still_constructs() -> None:
    enum_path = Path(__import__("enum").__file__)
    source = SourceFile.from_path(
        enum_path,
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    function = next(fn for fn in source.functions() if fn.name == "_is_internal_class")
    sugar = function.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1) or outcome is not None
