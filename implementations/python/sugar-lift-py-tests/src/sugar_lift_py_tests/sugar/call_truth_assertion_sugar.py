from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.ir import Formula, Term, atomic
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.object_truthiness import object_truth_formula
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar.witness_examples import call_truth_assertion_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class CallTruthAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.call-truth-assertion-sugar"

    call: Term
    call_body: SugarBody | None
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Call":
            return False
        if test.call_target_name() == "isinstance":
            return False
        return can_symbolic_term(test)

    @classmethod
    def witnesses(cls):
        return call_truth_assertion_witness()

    @classmethod
    def build(cls, site, ctx) -> "CallTruthAssertionSugar":
        test = site.assert_test()
        return cls(
            call=symbolic_term(
                test,
                owner="call truth assertion",
                import_aliases=getattr(ctx, "import_aliases", {}) or {},
                from_imports=getattr(ctx, "from_imports", {}) or {},
                name_resolver=getattr(ctx, "name_resolver", {}) or {},
                external_bridge_sink=getattr(ctx, "external_bridge_sink", None),
            ),
            call_body=_local_constructor_body(test, ctx),
            blame=site.blame,
        )

    def assertion_formula(self) -> Formula:
        return atomic("py.truthy", [self.call])

    def desugar(self, ctx):
        if self.call_body is None:
            return self.assertion_formula()
        call_outcome = self.call_body.reduce(ctx)
        if isinstance(call_outcome, Incomplete):
            return call_outcome
        value = complete_value(call_outcome, owner="CallTruthAssertionSugar call")
        if not isinstance(value, ObjectValue):
            return self.assertion_formula()
        return object_truth_formula(
            value,
            ctx,
            owner="CallTruthAssertionSugar",
            blame=self.blame,
        )


def _local_constructor_body(test, ctx) -> SugarBody | None:
    target = test.call_target_name()
    if target is None:
        return None
    import_target = test.call_import_target_name(
        getattr(ctx, "import_aliases", {}) or {},
        getattr(ctx, "from_imports", {}) or {},
    )
    if import_target is not None:
        return None
    function_node = (getattr(ctx, "name_resolver", None) or {}).get(target)
    if function_node is None:
        return None

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if SourceFragment.from_node(function_node, ctx.filename).observed != "ClassDef":
        return None
    return ctx.build_body(test, SugarRole.TERM)
