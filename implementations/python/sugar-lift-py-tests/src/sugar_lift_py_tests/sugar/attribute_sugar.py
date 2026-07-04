from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BoundVar, SymbolicValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.operations import AttributeLookupOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar.witness_examples import attribute_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeSugar(Sugar, role=SugarRole.TERM):
    term: Term | None
    receiver: SugarBody | None
    receiver_name: str | None
    name: str
    blame: str
    runtime_reason: str | None = None

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Attribute"

    @classmethod
    def witnesses(cls):
        return attribute_return_witness()

    @classmethod
    def build(cls, site, ctx) -> "AttributeSugar":
        if not can_symbolic_term(site):
            receiver = site.attr_receiver()
            return cls(
                term=None,
                receiver=None,
                receiver_name=None,
                name=site.attr_name(),
                blame=site.blame,
                runtime_reason=(
                    f"attribute receiver `{receiver.observed}` requires runtime "
                    "evaluation before attribute lookup"
                ),
            )
        return cls(
            term=symbolic_term(
                site,
                owner="attribute sugar",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            receiver=_projectable_receiver(site, ctx),
            receiver_name=_receiver_name(site),
            name=site.attr_name(),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if self.runtime_reason is not None:
            return _runtime_receiver_effect(self.blame, self.runtime_reason)
        if self.term is None:
            raise TypeError("AttributeSugar non-runtime path requires a term")
        if self.receiver is None:
            return Complete(SymbolicValue(self.term))
        if self.receiver_name is not None and not _temporal_has_binding(
            ctx, self.receiver_name
        ):
            return Complete(SymbolicValue(self.term))
        if self.receiver_name is not None and _temporal_binding_is_external_bridge(
            ctx, self.receiver_name
        ):
            return Complete(SymbolicValue(self.term))
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(receiver_outcome, owner="AttributeSugar receiver")
        if isinstance(receiver, SymbolicValue):
            return Complete(SymbolicValue(self.term))
        operation = AttributeLookupOperation(
            name=self.name,
            owner="AttributeSugar",
            blame=self.blame,
        )
        return perform_operation(
            owner="AttributeSugar",
            blame=self.blame,
            receiver=receiver,
            operation=operation,
            ctx=ctx,
        )


def _runtime_receiver_effect(blame: str, reason: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "attribute lookup runtime boundary: "
            f"{reason}. Python evaluates the receiver and descriptor hooks at "
            "runtime; keep as typed red until a narrower vendor-cited reduction "
            f"owns the shape. blame={blame}"
        )
    )


def _projectable_receiver(site, ctx) -> SugarBody | None:
    receiver = site.attr_receiver()
    if receiver.observed == "Name":
        return ctx.build_body(receiver, SugarRole.TERM)
    if receiver.observed == "Call" and _is_resolved_local_class_call(receiver, ctx):
        return ctx.build_body(receiver, SugarRole.TERM)
    return None


def _receiver_name(site) -> str | None:
    receiver = site.attr_receiver()
    if receiver.observed == "Name":
        return receiver.name_id()
    return None


def _temporal_has_binding(ctx, name: str) -> bool:
    return _temporal_binding_value(ctx, name) is not None


def _temporal_binding_value(ctx, name: str):
    temporal = ctx.temporal
    for binding in reversed(temporal.bindings):
        if binding.name == name:
            return binding.value
    return None


def _temporal_binding_is_external_bridge(ctx, name: str) -> bool:
    value = _temporal_binding_value(ctx, name)
    if not isinstance(value, BoundVar):
        return False
    sugar = getattr(value.source, "sugar", None)
    strategy = getattr(sugar, "strategy", None)
    return type(strategy).__name__ == "ExternalBridgeStrategy"


def _is_resolved_local_class_call(site, ctx) -> bool:
    target = (
        site.call_import_target_name(
            ctx.import_aliases or {},
            ctx.from_imports or {},
        )
        or site.call_target_name()
    )
    resolver = ctx.name_resolver or {}
    resolved_node = resolver.get(target)
    if resolved_node is None:
        return False
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    return SourceFragment.from_node(resolved_node, ctx.filename).observed == "ClassDef"
