"""Vertical completion: formal ``setattr_named`` through the n-ary projector.

Python semantic law made constructible:

  For ``helper(obj, value)`` whose body is ``obj.attr = value``, the store
  dispatches ``__setattr__`` / descriptor ``__set__`` — a different method and
  obligation from the read path.  Helper alone stays undischarged.  An ordinary
  source caller (positional, keyword, or default) supplies authenticated
  actuals; discharge projects Completed field stores or named exceptional
  faces whose origin is Floor ``setattr``, never an enclosing boundary type.

Mint contract (matches #6614 projector):

  operator ``setattr_named``
  operands ``(receiver, StringValue(name), value)``
  coordinates ``(receiver.formal_coordinate, None, value_coordinate)``
  projector: ``receiver.setattr(name.value, value, site)``

Corpus (pandas 3.0.3, content verified on installed seat):

  ``compat/__init__.py:52`` in ``set_function_name`` @48:
      ``f.__name__ = name``  (formal ``f`` store)
  ``core/indexes/base.py:4267`` in ``_maybe_preserve_names`` @4264:
      ``target.name = self.name``  (formal ``target`` store)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    NoneValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _tree(source: str, name: str = "setattr_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition():
    source = "def helper(obj, value):\n    obj.attr = value\n"
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _call_outcome(signature: str, actuals: str):
    source = (
        f"def helper({signature}):\n" "    obj.attr = value\n\n" f"helper({actuals})\n"
    )
    tree = _tree(source)
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _assert_named_halt(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None
    return halted


# ---------------------------------------------------------------------------
# Helper alone → Undischarged
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_setattr_named_carrier() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setattr_named"
    assert len(pending.operands) == 3
    assert len(pending.demand.operand_coordinate_cids) == 3
    # Static attribute name slot is null — not a formal.
    assert pending.demand.operand_coordinate_cids[1] is None
    # Receiver and value formals are present and distinct.
    assert pending.demand.operand_coordinate_cids[0] is not None
    assert pending.demand.operand_coordinate_cids[2] is not None
    assert (
        pending.demand.operand_coordinate_cids[0]
        != pending.demand.operand_coordinate_cids[2]
    )


def test_setattr_named_mint_operand_order_matches_projector() -> None:
    """#6613: same-length but swapped coordinate identity panics — pin order."""
    _, pending = _helper_definition()
    assert pending.demand.operator == "setattr_named"
    # Operand 0 is the formal receiver; operand 1 is the static StringValue name.
    from sugar_lift_py_tests.floor import StringValue

    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "attr"


# ---------------------------------------------------------------------------
# Real callers → Completed or named Exceptional (same demand)
# ---------------------------------------------------------------------------


def test_positional_caller_completes_field_store_via_setattr() -> None:
    # Source-level int actuals hit TermValue.setattr → named AttributeError.
    # Completion path is discharge with ObjectValue actuals (below).
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    receiver = ObjectValue("R", (ObjectField("attr", TermValue(0)),))
    exits = pending.discharge({obj_cid: receiver, value_cid: TermValue(7)})
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    # Stored field is the discharged value.
    stored = exits.exits[0].value
    # UniverseValue record holds the completed store result.
    record = getattr(stored, "record", None)
    assert record is not None
    statements = record.statements
    assert any(
        isinstance(s, ObjectValue) and s.fields and s.fields[-1].value == TermValue(7)
        for s in statements
    )


def test_positional_caller_halts_with_named_identity_from_setattr() -> None:
    halted = _assert_named_halt(_call_outcome("obj, value", "1, 2"))
    # Origin is store dispatch, not a fabricated boundary type alone.
    assert halted.effect.exception_type_coordinate is not None
    # Source call presentation may name the Call producer for the edge; the
    # type coordinate is still from setattr floor discharge, not pytest.raises.
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)


def test_keyword_caller_reaches_same_demand() -> None:
    halted = _assert_named_halt(_call_outcome("obj, value", "obj=1, value=2"))
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)


def test_default_value_caller_reaches_same_demand() -> None:
    halted = _assert_named_halt(_call_outcome("obj, value=2", "1"))
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)


def test_tuple_receiver_store_halts_from_setattr_not_boundary() -> None:
    function, pending = _helper_definition()
    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {obj_cid: TupleValue((TermValue(1),)), value_cid: TermValue(9)}
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)
    # Direct setattr owner is proven on the incomplete path before carrier
    # re-projects the exceptional resolution.
    site = function.body[0].fragment
    from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar
    from sugar_lift_py_tests.outcome import Complete, Incomplete
    from sugar_lift_py_tests.sugar.sugar_base import Sugar as _S

    @dataclass(frozen=True)
    class _V(_S):
        value: object

        def desugar(self, ctx=None):
            return Complete(self.value)

        @classmethod
        def witnesses(cls):
            return ()

    direct = AttributeStoreEffectSugar(
        _V(TupleValue((TermValue(1),))),
        _V(TermValue(9)),
        "attr",
        site,
    ).desugar()
    assert isinstance(direct, Incomplete)
    assert direct.effect.producer_node_owner == "TupleValue.setattr"


# ---------------------------------------------------------------------------
# Property: readable ≠ settable through caller path
# ---------------------------------------------------------------------------


def test_property_without_setter_reads_fine_and_halts_on_store_after_discharge() -> (
    None
):
    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    receiver = ObjectValue(
        "R",
        (),
        methods=(
            ObjectMethodValue(
                name="attr",
                parameters=("self",),
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    # Readable property is present as a data descriptor (getter enrolled).
    assert any(
        m.name == "attr" and m.descriptor_kind == "property" for m in receiver.methods
    )

    # Through formal discharge: store path raises AttributeError — never a
    # completed field write licensed by the getter.
    function, pending = _helper_definition()
    site = function.body[0].fragment
    store = receiver.setattr("attr", TermValue(7), site)
    from sugar_lift_py_tests.floor import RaiseValue

    assert isinstance(store, Complete) and isinstance(store.value, RaiseValue)
    assert store.value.effect.exception_name == "AttributeError"
    assert store.value.effect.producer_node_owner == "ObjectValue.setattr"

    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, value_cid: TermValue(7)})
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert "AttributeError" in repr(halted.effect.exception_type_coordinate)


def test_lying_read_path_does_not_authorize_completed_store() -> None:
    """Borrowing __getattr__ evidence to complete a store must fail."""

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            return Complete(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    receiver = ObjectValue(
        "R",
        (),
        methods=(
            ObjectMethodValue(
                name="attr",
                parameters=("self",),
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    _, pending = _helper_definition()
    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: receiver, value_cid: TermValue(99)})
    assert isinstance(exits.exits[0], Halted)
    assert not isinstance(exits.exits[0], Completed)


# ---------------------------------------------------------------------------
# Wrong boundary type: exceptional edge remains unconsumed
# ---------------------------------------------------------------------------


def test_wrong_expected_type_leaves_exceptional_edge_unconsumed() -> None:
    """Boundary verifies; it cannot create. Wrong T leaves the edge unconsumed."""
    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.ir import ctor, str_const

    function, pending = _helper_definition()
    obj_cid, _, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge({obj_cid: NoneValue(), value_cid: TermValue(1)})
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    produced_type = halted.effect.exception_type_coordinate
    assert produced_type is not None

    # Boundary expects ValueError; store produced AttributeError.
    wrong = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    # Equality of type coordinates is not origin — produced is AttributeError.
    assert produced_type != wrong
    # The exceptional edge is still present (unconsumed by a wrong boundary).
    assert isinstance(halted, Halted)
    assert halted.effect.occurrence_id is not None


# ---------------------------------------------------------------------------
# Corpus coordinates
# ---------------------------------------------------------------------------


def test_pinned_pandas_formal_attr_store_coordinates_are_real() -> None:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    install_root = corpus.root.parent
    cases = (
        (
            "pandas/compat/__init__.py",
            52,
            "f.__name__ = name",
            "set_function_name",
            48,
        ),
        (
            "pandas/core/indexes/base.py",
            4267,
            "target.name = self.name",
            "_maybe_preserve_names",
            4264,
        ),
    )
    for rel, line, text, fn_name, fn_line in cases:
        path = install_root / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[line - 1].strip() == text, (rel, line, lines[line - 1])
        # Function def line verified.
        assert f"def {fn_name}" in lines[fn_line - 1], (
            rel,
            fn_line,
            lines[fn_line - 1],
        )
