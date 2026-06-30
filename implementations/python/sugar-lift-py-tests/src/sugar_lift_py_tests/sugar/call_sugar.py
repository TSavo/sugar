from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.floor import StringValue, SymbolicValue
from sugar_lift_py_tests.ir import Formula, eq, make_var, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody

# A resolved callee's body is either a single TERM expression (`return <expr>`, a
# SugarBody) or a multi-statement universe (control flow / encoder, a FunctionBodyUniverse).
FunctionCallBody = SugarBody | FunctionBodyUniverse
_BODY_TYPES = (SugarBody, FunctionBodyUniverse)


@dataclass(frozen=True)
class RefuseStrategy:
    """Nothing resolves this call -- a clean, NAMED refusal (a FactoryGap), built where the
    fragment's blame lives and raised on reduce. A refusal is sound: it says exactly what is
    missing (a body, an imported `.proof`, or a sugar), never a silent lift, never a side door."""

    info: FactoryGapInfo

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        audit = FactoryAuditRow(
            role="term", status="refused", observed=self.info.observed,
            blame=self.info.blame, selected="CallSugar", candidates=["CallSugar"],
            message=self.info.message,
        )
        raise FactoryGap(self.info, audit)


@dataclass(frozen=True)
class BridgeStrategy:
    """A RESOLVED call. It carries the callee's contract -- the UNIVERSE (`f(args)`, the body
    walked over the formals) -- which the dig mints as the `::callable` function-contract, and
    it emits the bridge term `call:<callee>(args)` for an in-body callsite. The bridge is the
    use; the universe is the definition; both are dumb sugar the factory built (the body comes
    from `ctx.build_body`, the catalog), never a side-door constructor.

    (Absorbed from the former call constructor -- same body adapter, now reached only through
    the catalog. The in-body bridge EMIT exists; full enqueue-on-emit awaits the dig queue, so
    today the dig is still warranted by the assertion in `_dig_universe`.)
    """

    target_name: str
    argument: SugarBody
    body: FunctionCallBody

    def __post_init__(self) -> None:
        if not isinstance(self.argument, SugarBody):
            raise TypeError("BridgeStrategy argument must be factory-built")
        if not isinstance(self.body, _BODY_TYPES):
            raise TypeError("BridgeStrategy body must be factory-built")

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        # The bridge term for an in-body callsite: `call:<callee>(<arg term>)`, an
        # uninterpreted symbol the assert (or a binding through it) equates to the expected.
        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        arg = complete_value(self.argument.reduce(ctx), owner="BridgeStrategy argument")
        if not isinstance(arg, StringValue):
            raise ValueError("write more Floor for BridgeStrategy argument")
        return Complete(SymbolicValue(euf_call_term(self.target_name, [str_const(arg.value)])))

    # --- the UNIVERSE (used by the dig in _dig_universe, via the catalog) -------------------

    def factory_steps(self, function):
        if isinstance(self.body, SugarBody):
            return [("StringLiteralSugar", "Constant", function.body[0], "StringValue")]
        return self.body.factory_steps(function)

    def constraint_formulas(self, output: StringValue | None = None) -> list[Formula]:
        if isinstance(self.body, SugarBody):
            if output is None:
                raise ValueError("BridgeStrategy simple body requires an output value")
            return [eq(make_var("out"), str_const(output.value))]
        return self.body.constraint_formulas()

    def constraint_formula_steps(self) -> list[Formula | None]:
        if isinstance(self.body, SugarBody):
            return []
        return self.body.constraint_formula_steps()

    def callsite_fact_formulas(self, expected: StringValue) -> list[Formula]:
        if isinstance(self.body, SugarBody):
            return [eq(make_var("out"), str_const(expected.value))]
        argument = complete_value(self.argument.reduce(None), owner="BridgeStrategy argument")
        if not isinstance(argument, StringValue):
            raise ValueError("write more Floor for BridgeStrategy argument")
        return [
            eq(make_var(self.body.parameter), str_const(argument.value)),
            eq(make_var("out"), str_const(expected.value)),
        ]


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A call -- DUMB. `owns` is shape only; `build` is the ONLY place context decides (it
    picks the strategy by resolution); `desugar` is one line, delegating. Every Call-owning
    sugar declares `comes_before=("CallSugar",)`, so CallSugar is the fallback catching every
    call no specific sugar claimed -- resolved (BridgeStrategy) or not (RefuseStrategy)."""

    strategy: object

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Call"

    @classmethod
    def build(cls, fragment, ctx) -> "CallSugar":
        from sugar_lift_py_tests.factory.sugar_constructors import build_bridge_body
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        target = fragment.call_target_name()
        resolver = getattr(ctx, "name_resolver", None) or {}
        function_node = resolver.get(target)
        # RESOLVED + unary (the dig can walk the body) -> the bridge carries its universe.
        if (
            function_node is not None
            and target is not None
            and not fragment.call_has_keywords()
            and fragment.call_arg_count() == 1
        ):
            argument = ctx.build_body(fragment.call_args()[0], SugarRole.TERM)
            function = SourceFragment.from_node(function_node, ctx.filename)
            body = build_bridge_body(function, ctx)
            return cls(strategy=BridgeStrategy(target_name=target, argument=argument, body=body))
        # Otherwise: a clean, named refusal (write the body/.proof/sugar), never a silent lift.
        info = FactoryGapInfo(
            owner="python.factory", blame=fragment.blame, observed="Call", requested="term",
            fix=f"resolve call to '{target}' (local body, imported .proof, or a sugar)",
        )
        return cls(strategy=RefuseStrategy(info))

    def desugar(self, ctx) -> Outcome:
        return self.strategy.emit(self, ctx)
