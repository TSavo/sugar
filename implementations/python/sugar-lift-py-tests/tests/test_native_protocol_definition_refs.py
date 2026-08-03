from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import (
    NativeDefinitionCoordinateGapV1,
    NativeProtocolSlot,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, make_var
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _coord(start: int) -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, start, 1, start + 1)


def test_native_protocol_slots_share_one_authenticated_definition_door():
    receiver, definition = _coord(2), _coord(20)
    refs = ResolvedContractRefsV1(
        "blake3-512:" + "b" * 128,
        "blake3-512:" + "c" * 128,
        {},
        {(receiver, NativeProtocolSlot.CONTEXT_EXIT): definition},
    )
    assert (
        refs.require_native_definition(receiver, NativeProtocolSlot.CONTEXT_EXIT)
        == definition
    )
    gap = refs.require_native_definition(receiver, NativeProtocolSlot.TRUTH)
    assert isinstance(gap, NativeDefinitionCoordinateGapV1)
    assert gap.reason.startswith("authenticated source definition")


def test_formal_truth_is_a_deferred_native_operation_with_unary_discharge():
    source = "def truth(receiver):\n    return bool(receiver)\n"
    tree = SourceFile((source, "truth.py", blake3_512_of(source.encode())))
    site = next(tree.functions()).fragment
    locus = _coord(0)
    formal = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=locus.source_cid,
        owner_definition_locus=locus,
        declaration_locus=locus,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="receiver",
        sort=PrimitiveSort("Value"),
    )
    outcome = SymbolicValue(make_var("receiver"), formal).truth(site)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    exits = outcome.discharge({formal.coordinate_cid: TermValue(1)})
    assert isinstance(exits.exits[0], Completed)
