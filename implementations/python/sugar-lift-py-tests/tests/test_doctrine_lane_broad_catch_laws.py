"""Doctrine laws for fleet-agy-1 lane: broad catches must not swallow panics.

Audit (manager_summary_derivation / manager_protocol_construction /
binding_state / generator_construction) found two live offenders:

1. ``GeneratorConstructionV1._guard_truth`` / ``_guard_formula`` catch
   ``BaseException`` and return ``None``, reclassifying ``ConstructionPanic``
   as ``GeneratorTransitionGapV1(observed='If carrying a suspension')``.
   ``ConstructionPanic`` is deliberately a BaseException so ordinary
   ``except Exception`` cannot silence it — catching BaseException undoes that.

2. ``binding_state._semantic_value_cid_for_bound_node`` catches ``Exception``
   (including ``SugarNotWritten``) and soft-succeeds with the node shape CID,
   so ``seal_bound_binding_entry_v1`` can mint sealed testimony after sugar
   refused. Seal must stay loud when value construction refused.

These instruments stay green when production refuses soft-seals: ConstructionPanic
propagates from guard truth; SugarNotWritten refuses seal. No carrier/ExitSet,
no silent None soft-greens.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    ReturnStepV1,
    YieldStepV1,
)
from sugar_lift_py_tests.ir import num
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BindingStateWireGap,
    RuntimeBindingEntryFactoryV1,
    seal_bound_binding_entry_v1,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _constant_entry():
    source = "def gen():\n    bound = 1\n    yield bound\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    function = next(SourceFile(path_source(path)).functions())
    value = next(node for node in function.walk() if node.kind == "Constant")
    factory = RuntimeBindingEntryFactoryV1(cid_of_json({"scope": "doctrine-audit"}))
    entry = factory.mint_entry(
        binding_site=value.fragment,
        projection_path=("value", 0),
        state=value,
    )
    return value, entry


def test_generator_guard_construction_panic_must_not_become_suspension_gap():
    """Law: ConstructionPanic from guard.truth propagates; never BaseException→None.

    Illegal shape (live offender):
        try: truth(...); except BaseException: return None
        → GeneratorTransitionGapV1(observed='If carrying a suspension')

    Replacement: let ConstructionPanic propagate (it is BaseException by design),
    or map only non-panic undecided outcomes to the suspension gap. Never catch
    BaseException around floor truth.
    """
    info = ConstructionGap(
        owner="doctrine.guard-truth",
        blame="guard-site",
        observed="incomplete guard floor",
        requested="guard truth value",
        fix="implement the guard floor; do not catch BaseException",
    )

    class PanicGuard:
        def truth(self, site):
            del site
            raise ConstructionPanic(info)

    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="audit:guard:1",
        frame_coordinate="frame:audit",
        binding_state=(),
        steps=(
            IfStepV1(
                PanicGuard(),
                (YieldStepV1(num(1)),),
                (ReturnStepV1(num(2)),),
                "frag:audit-if",
            ),
        ),
    )

    with pytest.raises(ConstructionPanic) as raised:
        machine.resume()
    assert raised.value.info.owner == "doctrine.guard-truth"
    # Twin: must not reclassify as the weaker suspension gap.
    try:
        machine.resume()
    except ConstructionPanic:
        return
    except Exception as other:  # pragma: no cover - failure mode documentation
        pytest.fail(
            f"reclassified ConstructionPanic as {type(other).__name__}: {other}"
        )
    else:  # pragma: no cover
        pytest.fail(
            "ConstructionPanic was swallowed; expected raise, got a non-raising result"
        )


def test_generator_guard_construction_panic_is_not_if_carrying_suspension():
    """Lying twin of the BaseException swallow: suspension gap must not impersonate panic."""
    info = ConstructionGap(
        owner="doctrine.guard-truth",
        blame="guard-site",
        observed="incomplete guard floor",
        requested="guard truth value",
        fix="implement the guard floor; do not catch BaseException",
    )

    class PanicGuard:
        def truth(self, site):
            del site
            raise ConstructionPanic(info)

    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="audit:guard:2",
        frame_coordinate="frame:audit",
        binding_state=(),
        steps=(
            IfStepV1(
                PanicGuard(),
                (YieldStepV1(num(1)),),
                (ReturnStepV1(num(2)),),
                "frag:audit-if-2",
            ),
        ),
    )
    # Document the live offender class for the fix-forward PR: today this returns
    # GeneratorTransitionGapV1 instead of raising. The law forbids that outcome.
    result = None
    try:
        result = machine.resume()
    except ConstructionPanic:
        return  # green when production is fixed
    assert not isinstance(result, GeneratorTransitionGapV1), (
        "ConstructionPanic was reclassified as GeneratorTransitionGapV1 "
        f"(observed={getattr(result, 'observed', None)!r}); "
        "fix=stop catching BaseException in _guard_truth/_guard_formula"
    )


def test_seal_refuses_when_node_sugar_raises_sugar_not_written():
    """Law: SugarNotWritten from node.sugar() must prevent sealing.

    Illegal shape (live offender):
        try: node.sugar(); except Exception: return node_construction_shape_cid(node)
        → seal_bound_binding_entry_v1 succeeds with shape-derived testimony

    Replacement: re-raise SugarNotWritten / map only non-refusal misses, or
    refuse seal with BindingStateWireGap. Never mint sealed testimony from a
    value whose sugar refused.
    """
    value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        with pytest.raises((SugarNotWritten, BindingStateWireGap)):
            seal_bound_binding_entry_v1(entry)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]


def test_seal_must_not_succeed_after_sugar_not_written():
    """Lying twin: successful seal after SugarNotWritten is the doctrine crime."""
    _value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        with pytest.raises((SugarNotWritten, BindingStateWireGap)):
            seal_bound_binding_entry_v1(entry)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]


def test_mutation_twin_tampered_seal_coordinate_still_refuses_after_sugar_refusal():
    """Mutation twin: stale coordinate cannot launder a refused sugar into a seal."""
    from dataclasses import replace

    _value, entry = _constant_entry()
    real_sugar = Node.sugar

    def refusing_sugar(self):
        raise SugarNotWritten(
            blame=self.fragment,
            owner="doctrine.seal-sugar",
            observed="sugar refused for bound value",
            requested="written constructed sugar",
            fix="write sugar or refuse seal; do not fall back to shape CID",
        )

    Node.sugar = refusing_sugar  # type: ignore[method-assign]
    try:
        tampered = replace(
            entry,
            coordinate=replace(entry.coordinate, cid="blake3-512:" + "f" * 128),
        )
        with pytest.raises((SugarNotWritten, BindingStateWireGap, ValueError)):
            seal_bound_binding_entry_v1(tampered)
    finally:
        Node.sugar = real_sugar  # type: ignore[method-assign]
