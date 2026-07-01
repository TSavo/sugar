from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.operations import AttributeLookupOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeSugar(Sugar, role=SugarRole.TERM):
    term: Term
    receiver: SugarBody | None
    name: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Attribute" and can_symbolic_term(site)

    @classmethod
    def build(cls, site, ctx) -> "AttributeSugar":
        return cls(
            term=symbolic_term(
                site,
                owner="attribute sugar",
                import_aliases=getattr(ctx, "import_aliases", {}) or {},
                from_imports=getattr(ctx, "from_imports", {}) or {},
                name_resolver=getattr(ctx, "name_resolver", {}) or {},
                external_bridge_sink=getattr(ctx, "external_bridge_sink", None),
            ),
            receiver=_projectable_receiver(site, ctx),
            name=site.attr_name(),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if self.receiver is None:
            return Complete(SymbolicValue(self.term))
        try:
            receiver_outcome = self.receiver.reduce(ctx)
        except FactoryGap as gap:
            if _is_constructor_gap(gap):
                raise
            return Complete(SymbolicValue(self.term))
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = getattr(receiver_outcome, "value", None)
        if isinstance(receiver, SymbolicValue) or not hasattr(receiver, "attribute_with"):
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
            method_name="attribute_with",
            operation=operation,
            ctx=ctx,
        )


def _is_constructor_gap(gap: FactoryGap) -> bool:
    requested = gap.info.get("requested", "")
    fix = gap.info.get("fix", "")
    return "constructor" in requested or "constructor" in fix


def _projectable_receiver(site, ctx) -> SugarBody | None:
    receiver = site.attr_receiver()
    if receiver.observed == "Name":
        return ctx.build_body(receiver, SugarRole.TERM)
    if receiver.observed == "Call" and _is_resolved_local_class_call(receiver, ctx):
        return ctx.build_body(receiver, SugarRole.TERM)
    return None


def _is_resolved_local_class_call(site, ctx) -> bool:
    target = site.call_import_target_name(
        getattr(ctx, "import_aliases", {}) or {},
        getattr(ctx, "from_imports", {}) or {},
    ) or site.call_target_name()
    resolver = getattr(ctx, "name_resolver", None) or {}
    resolved_node = resolver.get(target)
    if resolved_node is None:
        return False
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    return SourceFragment.from_node(resolved_node, ctx.filename).observed == "ClassDef"
