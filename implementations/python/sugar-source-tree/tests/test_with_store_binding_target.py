"""``with M() as <store target>:`` — the as-clause is Python's own assignment.

Two shapes, both taken from real corpus sites and renamed:

    with get_handle(...) as self.handles:          # Attribute store target
    with builder.if_else(cond) as (yes, no):       # Tuple destructure target

Both used to be one hard `UnsupportedWithBindingTarget` refusal whose fix line
read "leave destructuring and attribute targets loud". They are not a second
binding mechanism: Python's as-clause IS an assignment, and `Assign` is already
total over attribute / subscript / tuple / nested / starred targets. So the
capability is a REWRITE, not a new arm — `With._bind_store_target` normalizes
the site into `<target> = ObservationRef(enter_slot)` as the first body
statement and inherits `Assign`'s totality. The With node stops knowing about
target shapes entirely.

What deliberately did NOT change:

- ``as <Name>`` still discharges by SUBSTITUTION (loads rewritten to
  ObservationRef), which is the stronger stated discharge. It is not routed
  through a store.
- The EffectBoundary contract still refuses ANY as-binding. Its projection is
  not authenticated, and the refusal is now total over every target shape
  rather than over Name targets only.
- A site whose manager never resolved to a ProtocolResource contract is not
  rewritten and stays exactly as loud as it was.

Each law carries a truthful twin and a lying twin.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExitContractV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import UnsupportedWithBindingTarget
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------- tree fixture


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _base_ref(use_site, *, signature, semantics) -> ContextManagerContractRefV1:
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=signature,
        semantics=semantics,
    )


def _resource_ref(use_site) -> ContextManagerContractRefV1:
    return _base_ref(
        use_site,
        signature=ImportSignatureV2(()),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
        ),
    )


def _boundary_ref(use_site) -> ContextManagerContractRefV1:
    return _base_ref(
        use_site,
        signature=ImportSignatureV2(
            (
                CallParameterV1(
                    "expected_exception",
                    PrimitiveSort("Value"),
                    PositionalOrKeywordV1(),
                    True,
                    NoDefaultV1(),
                ),
            )
        ),
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            OptionalFormalArgumentProjectionV1(0),
            ExceptionInfoBindingV1(),
        ),
    )


def _function_sugar(tmp_path, source: str, *, ref=_resource_ref, name="f"):
    path = tmp_path / "store_target.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    rows = {}
    for node in probe.nodes():
        if node.kind != "With":
            continue
        for item in node.items:
            coordinate = _coordinate(item.context_expr)
            rows[coordinate] = ref(coordinate)
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    source_file = SourceFile(identity, construction_context=context)
    for fn in source_file.functions():
        if fn.name == name:
            return fn.sugar()
    raise AssertionError(f"no function {name}")


def _resource_of(sugar):
    found = []

    def walk(node):
        if isinstance(node, WithResourceSugar):
            found.append(node)
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return found


HEADER = "from dependency import manager\n"

# Renamed from the real corpus attribute-target site.
ATTRIBUTE_TARGET = HEADER + (
    "def f(self):\n"
    "    with manager() as self.handles:\n"
    "        return self.handles\n"
)

# Renamed from the real corpus tuple-destructure site.
TUPLE_TARGET = HEADER + (
    "def f():\n" "    with manager() as (yes, no):\n" "        return yes\n"
)

NAME_TARGET = HEADER + (
    "def f():\n" "    with manager() as entered:\n" "        return entered\n"
)

NO_TARGET = HEADER + ("def f():\n    with manager():\n        return 1\n")


# ------------------------------------------------- LAW: attribute store target


def test_attribute_target_constructs_instead_of_refusing(tmp_path):
    """TRUTHFUL: the real `as self.handles` shape now constructs."""
    resources = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))
    assert len(resources) == 1, f"expected one resource with, got {len(resources)}"


def test_lying_attribute_target_is_not_silently_dropped(tmp_path):
    """LYING: constructing must not mean the store vanished.

    The enter-result slot MUST be bound — an attribute store whose RHS is an
    unbound slot would be a fabricated binding. Assert the slot is absent and
    show that fails.
    """
    resource = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))[0]
    with pytest.raises(AssertionError):
        assert resource.enter_slot_id is None, "a bound target must bind its slot"


def test_attribute_target_binds_the_enter_result_slot(tmp_path):
    """LAW: the store's RHS is the authenticated enter-result projection."""
    resource = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))[0]
    assert resource.enter_slot_id == f"{resource.manager_slot_id}#enter_result"


# ---------------------------------------------------- LAW: tuple destructure


def test_tuple_target_constructs_instead_of_refusing(tmp_path):
    """TRUTHFUL: the real `as (yes, no)` shape now constructs."""
    resources = _resource_of(_function_sugar(tmp_path, TUPLE_TARGET))
    assert len(resources) == 1, f"expected one resource with, got {len(resources)}"


def test_tuple_target_binds_the_enter_result_slot(tmp_path):
    """LAW: a destructure binds the same one slot; elements project from it."""
    resource = _resource_of(_function_sugar(tmp_path, TUPLE_TARGET))[0]
    assert resource.enter_slot_id == f"{resource.manager_slot_id}#enter_result"


def test_lying_tuple_target_does_not_bind_a_second_manager(tmp_path):
    """LYING: a destructure is ONE manager, not one per element.

    A rewrite that treated the tuple as multiple items would build two
    resources. Exact cardinality — `!= 1` is satisfied by 0 and by 2.
    """
    resources = _resource_of(_function_sugar(tmp_path, TUPLE_TARGET))
    with pytest.raises(AssertionError):
        assert len(resources) == 2, "a destructure must not multiply the manager"


# ------------------------------ LAW: the store is the FIRST body statement


def test_store_runs_inside_the_block_as_the_first_body_statement(tmp_path):
    """LAW: the store lands where Python runs it — after `__enter__`, inside
    the block — so a halting store is a body edge the contract's `__exit__`
    still covers. The body is therefore LONGER than the source body."""
    stored = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))[0]
    plain = _resource_of(_function_sugar(tmp_path, NAME_TARGET))[0]
    assert len(stored.body) == len(plain.body) + 1


def test_lying_store_is_not_hoisted_out_of_the_block(tmp_path):
    """LYING: hoisting the store outside the With would leave the body the same
    length as the substituted Name case. Assert that and show it fails."""
    stored = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))[0]
    plain = _resource_of(_function_sugar(tmp_path, NAME_TARGET))[0]
    with pytest.raises(AssertionError):
        assert len(stored.body) == len(plain.body)


# --------------------------------- LAW: the Name path is NOT routed to a store


def test_name_target_still_discharges_by_substitution(tmp_path):
    """LAW: `as <Name>` keeps the STRONGER stated discharge — no store injected.

    This is the non-regression that matters most: the overwhelming majority of
    corpus as-bindings are simple names, and routing them through a store would
    trade a stated binding for a derived one.
    """
    plain = _resource_of(_function_sugar(tmp_path, NAME_TARGET))[0]
    bare = _resource_of(_function_sugar(tmp_path, NO_TARGET))[0]
    assert len(plain.body) == len(bare.body), "a Name target must inject no store"
    assert plain.enter_slot_id is not None
    assert bare.enter_slot_id is None


def test_lying_name_path_is_not_vacuous(tmp_path):
    """LYING: the equality above would fail against a shape that DOES store."""
    stored = _resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))[0]
    bare = _resource_of(_function_sugar(tmp_path, NO_TARGET))[0]
    with pytest.raises(AssertionError):
        assert len(stored.body) == len(bare.body)


# ------------------------- LAW: the EffectBoundary refusal stays TOTAL


def test_effect_boundary_refuses_a_store_target(tmp_path):
    """LAW: widening the resource arm must not widen the assertion arm.

    #6391 authenticated an EffectBoundary observation slot for a NAME binding.
    It did not authenticate a STORE, and `_bind_store_target` deliberately
    declines to rewrite this contract. So a store target here must stay loud.

    Without the paired production arm this is exactly where a binding would be
    silently DROPPED: `as_name` is None for a store target, so the slot would
    quietly resolve to None and the site would construct having thrown away the
    binding the source wrote. A dropped binding is the one outcome neither
    contract admits.
    """
    with pytest.raises(UnsupportedWithBindingTarget):
        _function_sugar(tmp_path, ATTRIBUTE_TARGET, ref=_boundary_ref)


def test_effect_boundary_admits_a_name_target_through_its_observation_slot(tmp_path):
    """LAW (#6391, milestone #2's): a NAME binding IS admitted here.

    This arm used to assert a refusal. That refusal was retired when the
    contract's observation projection became authenticated, so the twin is
    retargeted rather than deleted — it now pins that the resource-side change
    did NOT regress the assertion side's new capability.
    """
    _function_sugar(tmp_path, NAME_TARGET, ref=_boundary_ref)


def test_lying_effect_boundary_refusal_is_not_unconditional(tmp_path):
    """LYING: the refusal above is caused by the STORE TARGET, not the contract.

    Same boundary contract, no as-clause, constructs fine.
    """
    _function_sugar(tmp_path, NO_TARGET, ref=_boundary_ref)


# --------------------------------------- LAW: unresolved managers stay loud


def test_unresolved_store_target_is_not_admitted_by_the_rewrite(tmp_path):
    """LAW: the rewrite is not an admission door.

    With no resolution table row, the site must stay typed-loud exactly as it
    did before — the rewrite fires only for an authenticated ProtocolResource.
    """
    path = tmp_path / "unresolved.py"
    path.write_text(ATTRIBUTE_TARGET, encoding="utf-8")
    identity = path_source(str(path))
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType({}))
    )
    source_file = SourceFile(identity, construction_context=context)
    from sugar_source_tree.panic import SourceTreePanic

    with pytest.raises(SourceTreePanic):
        next(fn for fn in source_file.functions() if fn.name == "f").sugar()


def test_lying_unresolved_case_is_not_failing_for_an_unrelated_reason(tmp_path):
    """LYING: the same source WITH a resolution row constructs."""
    assert len(_resource_of(_function_sugar(tmp_path, ATTRIBUTE_TARGET))) == 1
