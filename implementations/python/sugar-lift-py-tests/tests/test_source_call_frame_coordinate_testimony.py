from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.source_call_frame import (
    BoundSourceCallActualsV1,
    MutableGlobalBindingV1,
    SourceCallBindingGap,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _frame(*, name: str = "helper", filename: str = "bound_coordinates.py"):
    source = f"def {name}(left, right=2):\n    return left + right\n"
    tree = SourceFile(
        (source, filename, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.source_visible_call_frame().with_native_operation_projection(
        function.formal_coordinates(), function.sugar().desugar(None)
    )


def _vararg_frame(*, filename: str = "bound_vararg_coordinates.py"):
    source = "def helper(*values):\n    return values[0]\n"
    tree = SourceFile(
        (source, filename, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.source_visible_call_frame()


def test_vararg_binder_retains_authenticated_child_coordinate_actuals() -> None:
    frame = _vararg_frame()
    first = TermValue(1)
    second = TermValue(2)

    bound = frame.bind_actuals((first, second), ())

    assert bound.actuals == (TupleValue((first, second)),)
    assert tuple(pair.coordinate for pair in bound.projected_pairs) == (
        frame.formal_coordinates[0].project("variadic", 0),
        frame.formal_coordinates[0].project("variadic", 1),
    )
    assert tuple(pair.actual for pair in bound.projected_pairs) == (first, second)


@pytest.mark.parametrize("variant", ("wrong-child", "foreign-root"))
def test_vararg_binder_refuses_cross_wired_child_projection(variant: str) -> None:
    frame = _vararg_frame()
    foreign = _vararg_frame(filename="foreign_vararg_coordinates.py")
    first = TermValue(1)
    truthful = frame.bind_actuals((first,), ())
    child = truthful.projected_pairs[0]
    coordinate = (
        frame.formal_coordinates[0].project("variadic", 1)
        if variant == "wrong-child"
        else foreign.formal_coordinates[0].project("variadic", 0)
    )

    with pytest.raises(SourceCallBindingGap, match="projected formal coordinate"):
        BoundSourceCallActualsV1(
            truthful.actuals,
            truthful.formal_coordinates,
            truthful.native_formal_coordinates,
            (replace(child, coordinate=coordinate),),
        )


def test_binder_returns_ordered_typed_coordinate_testimony() -> None:
    frame = _frame()
    left = TermValue(1)
    bound = frame.bind_actuals((left,), ())

    assert isinstance(bound, BoundSourceCallActualsV1)
    assert bound.actuals[0] is left
    assert bound.formal_coordinates == frame.formal_coordinates
    assert bound.native_formal_coordinates == frame.native_operation_formal_coordinates
    assert tuple(pair.actual for pair in bound.pairs) == bound.actuals
    assert tuple(pair.coordinate for pair in bound.pairs) == frame.formal_coordinates
    assert tuple(bound.by_native_formal_coordinate) == tuple(
        coordinate.coordinate_cid
        for coordinate in frame.native_operation_formal_coordinates
    )


def test_bound_actuals_equality_requires_authenticated_coordinate_testimony() -> None:
    """Equal values cannot erase their source-coordinate authority."""
    frame = _frame()
    foreign = _frame(name="other", filename="foreign_equality.py")
    values = (TermValue(1), TermValue(2))
    truthful = BoundSourceCallActualsV1(
        values,
        frame.formal_coordinates,
        frame.native_operation_formal_coordinates,
    )
    lying = BoundSourceCallActualsV1(
        values,
        foreign.formal_coordinates,
        foreign.native_operation_formal_coordinates,
    )

    assert truthful != lying
    assert truthful != values
    assert values != truthful


def test_bound_actuals_requires_explicit_value_projection() -> None:
    """Authenticated testimony cannot masquerade as an unlabelled sequence."""
    frame = _frame()
    values = (TermValue(1), TermValue(2))
    bound = BoundSourceCallActualsV1(
        values,
        frame.formal_coordinates,
        frame.native_operation_formal_coordinates,
    )

    assert bound.actuals == values
    assert not isinstance(bound, Sequence)
    with pytest.raises(TypeError):
        tuple(bound)


@pytest.mark.parametrize("variant", ("missing", "duplicate", "reordered", "foreign"))
def test_binder_refuses_corrupt_formal_coordinate_roster(variant: str) -> None:
    frame = _frame()
    coordinates = frame.formal_coordinates
    if variant == "missing":
        corrupt = coordinates[:-1]
    elif variant == "duplicate":
        corrupt = (coordinates[0], coordinates[0])
    elif variant == "reordered":
        corrupt = tuple(reversed(coordinates))
    else:
        corrupt = (
            replace(coordinates[0], scope_owner_cid="blake3-512:" + "00" * 64),
            coordinates[1],
        )

    with pytest.raises(SourceCallBindingGap, match="formal coordinate roster"):
        replace(frame, formal_coordinates=corrupt).bind_actuals(
            (TermValue(1), TermValue(2)), ()
        )


def test_binder_refuses_cross_wired_native_formal_roster() -> None:
    frame = _frame()
    with pytest.raises(SourceCallBindingGap, match="native formal coordinate roster"):
        replace(
            frame,
            native_operation_formal_coordinates=tuple(
                reversed(frame.native_operation_formal_coordinates)
            ),
        ).bind_actuals((TermValue(1), TermValue(2)), ())


def test_binder_refuses_wholly_foreign_binding_roster() -> None:
    frame = _frame()
    foreign = _frame(name="other", filename="foreign_bindings.py")

    with pytest.raises(SourceCallBindingGap, match="scope owner"):
        replace(frame, formal_coordinates=foreign.formal_coordinates).bind_actuals(
            (TermValue(1), TermValue(2)), ()
        )


def test_frame_refuses_mutable_global_binding_from_foreign_source() -> None:
    frame = _frame()
    foreign = _frame(name="other", filename="foreign_mutable_global.py")
    occurrence = foreign.owner.fragment.seal()
    binding = MutableGlobalBindingV1(
        source_cid=foreign.source_identity_cid,
        binding_occurrence=occurrence,
        name="REGISTRY",
        kind="dict",
        term={"kind": "test-mutable-global-term"},
        line=foreign.owner.lineno,
        col=foreign.owner.col_offset,
    )

    with pytest.raises(SourceCallBindingGap, match="mutable global binding source"):
        replace(frame, mutable_global_bindings=(binding,))


def test_binder_refuses_stale_binding_coordinate_cid() -> None:
    frame = _frame()
    stale = replace(frame.formal_coordinates[0], cid="blake3-512:" + "00" * 64)

    with pytest.raises(SourceCallBindingGap, match="CID"):
        replace(
            frame, formal_coordinates=(stale, frame.formal_coordinates[1])
        ).bind_actuals((TermValue(1), TermValue(2)), ())


def test_binder_refuses_same_signature_foreign_native_roster() -> None:
    frame = _frame()
    foreign = _frame(name="other", filename="foreign_native.py")

    with pytest.raises(SourceCallBindingGap, match="native formal coordinate roster"):
        replace(
            frame,
            native_operation_formal_coordinates=foreign.native_operation_formal_coordinates,
        ).bind_actuals((TermValue(1), TermValue(2)), ())


def test_binder_refuses_foreign_pending_carrier_demand() -> None:
    frame = _frame()
    foreign = _frame(name="other", filename="foreign_pending.py")

    with pytest.raises(SourceCallBindingGap, match="pending carrier demand"):
        replace(
            frame, pending_native_operation=foreign.pending_native_operation
        ).bind_actuals((TermValue(1), TermValue(2)), ())


def test_binder_refuses_wrong_native_parameter_kind() -> None:
    frame = _frame()
    original = frame.native_operation_formal_coordinates[0]
    wrong = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=original.owner_source_identity_cid,
        owner_definition_locus=original.owner_definition_locus,
        declaration_locus=original.declaration_locus,
        ordinal=original.ordinal,
        parameter_kind="keyword-only",
        declared_name=original.declared_name,
        sort=PrimitiveSort("Value"),
    )

    with pytest.raises(SourceCallBindingGap, match="native formal coordinate roster"):
        replace(
            frame,
            native_operation_formal_coordinates=(
                wrong,
                frame.native_operation_formal_coordinates[1],
            ),
        ).bind_actuals((TermValue(1), TermValue(2)), ())


@pytest.mark.parametrize("coordinate_kind", ("formal", "native"))
@pytest.mark.parametrize("delta", (-1, 1))
def test_bound_result_rejects_missing_or_extra_coordinate(
    coordinate_kind: str, delta: int
) -> None:
    frame = _frame()
    actuals = (TermValue(1), TermValue(2))
    formal = frame.formal_coordinates
    native = frame.native_operation_formal_coordinates
    roster = formal if coordinate_kind == "formal" else native
    corrupt = roster[:-1] if delta < 0 else (*roster, roster[-1])

    with pytest.raises(SourceCallBindingGap, match="bound actual coordinate arity"):
        BoundSourceCallActualsV1(
            actuals,
            corrupt if coordinate_kind == "formal" else formal,
            corrupt if coordinate_kind == "native" else native,
        )


# ---------------------------------------------------------------------------
# The carried term is a VALUE; the wire term stays wire-shaped
# ---------------------------------------------------------------------------


def _binding(term):
    frame = _frame(filename="mutable_global_value.py")
    return MutableGlobalBindingV1(
        source_cid=frame.source_identity_cid,
        binding_occurrence=frame.owner.fragment.seal(),
        name="_global_config",
        kind="dict",
        term=term,
        line=frame.owner.lineno,
        col=frame.owner.col_offset,
    )


def _pin_term():
    from sugar_lift_python_source.value_pins import mutable_global_pin_term

    return mutable_global_pin_term("_global_config", "dict")


def test_a_carried_pin_term_canonicalizes_as_a_value():
    """The seat behind 78 frontier rows.

    Every `with pandas.option_context(...)` digs `_config/config.py`, whose
    module-level mutable globals are pinned. The pin already does the honest
    thing -- it refuses to snapshot the mutable value and carries only the loud
    ``(name, kind)`` coordinate -- but the wire dialect spells that fixed
    two-element coordinate ``list``, so ConstructedValueV2 refused the very
    repair the pin had already made.
    """
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    binding = _binding(_pin_term())
    assert isinstance(binding.term["args"], tuple)
    assert constructed_value_cid_v2(binding.term).startswith("blake3-512:")


def test_respelling_the_carried_term_moves_no_coordinate():
    """Content is unchanged, so the binding CID must be unchanged.

    The CID is taken of the wire spelling before the slot is respelled --
    ``cid_of_json`` admits a list and refuses a tuple, so this ordering is
    load-bearing rather than incidental.
    """
    from sugar_lift_python_source.canonical import cid_of_json

    binding = _binding(_pin_term())
    expected = cid_of_json(
        {
            "kind": "mutable-global-binding",
            "schemaVersion": "1",
            "sourceCid": binding.source_cid,
            "bindingOccurrence": binding.binding_occurrence.to_dict(),
            "name": binding.name,
            "mutableKind": binding.kind,
            # the WIRE spelling, list and all
            "term": _pin_term(),
            "line": binding.line,
            "col": binding.col,
        }
    )
    assert binding.cid == expected


def test_the_mutable_container_category_was_not_broadened():
    """A real list in a real slot must still refuse.

    If this passes only because ``_cv2_entries`` learned to absorb lists, the
    78 rows were bought by authenticating a moment.
    """
    from sugar_source_tree.binding_state import (
        ConstructedValueCategoryGap,
        constructed_value_cid_v2,
    )

    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2({"kind": "ctor", "args": [{"kind": "var"}]})
    assert "MUTABLE container" in str(caught.value)
    assert "builtins.list" in str(caught.value)


def test_a_term_member_outside_the_wire_categories_refuses_loudly():
    """Categories are CLOSED: the respelling is not a reflective deep-copy."""
    with pytest.raises(SourceCallBindingGap, match="not a wire term value"):
        _binding({"kind": "ctor", "args": [object()]})
