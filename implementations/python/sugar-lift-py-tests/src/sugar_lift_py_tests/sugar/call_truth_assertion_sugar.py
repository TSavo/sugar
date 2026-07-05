from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.ir import Formula, Term, atomic, bool_const, eq
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
    boolean_call: bool
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
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            call_body=_local_constructor_body(test, ctx),
            boolean_call=_local_boolean_function_call(test, ctx),
            blame=site.blame,
        )

    def assertion_formula(self) -> Formula:
        if self.boolean_call:
            return eq(self.call, bool_const(True))
        return atomic("py.truthy", [self.call])

    def _build(self, ctx):
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
        ctx.import_aliases or {},
        ctx.from_imports or {},
    )
    if import_target is not None:
        return None
    function_node = (ctx.name_resolver or {}).get(target)
    if function_node is None:
        return None

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if SourceFragment.from_node(function_node, ctx.filename).observed != "ClassDef":
        return None
    return ctx.build_body(test, SugarRole.TERM)


def _local_boolean_function_call(test, ctx) -> bool:
    target = test.call_target_name()
    if target is None:
        return False
    import_target = test.call_import_target_name(
        ctx.import_aliases or {},
        ctx.from_imports or {},
    )
    if import_target is not None:
        return False
    function_node = (ctx.name_resolver or {}).get(target)
    if function_node is None:
        return False

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    function = SourceFragment.from_node(function_node, ctx.filename)
    if function.observed != "FunctionDef":
        return False
    body = function.function_body()
    if len(body) != 1 or body[0].observed != "Return":
        return False
    value = body[0].return_value()
    if value is None:
        return False
    if value.observed in {"Compare", "BoolOp"}:
        return True
    if value.observed == "PrimitiveLiteral":
        return isinstance(value.literal_value(), bool)
    return False
