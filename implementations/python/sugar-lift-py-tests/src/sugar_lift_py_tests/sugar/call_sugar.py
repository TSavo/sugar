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
        # Emit the bridge AND enqueue its dig -- one act. `call:<callee>(arg)` is a POINTER to
        # the callee's tower; the instant we emit it, that tower is OWED a contract. A bridge
        # with nothing defining `call:<callee>(arg)` is a dangling free symbol the ground-
        # contradiction check cannot fold (a false discharge), so pointer and obligation are
        # inseparable: we append the dig to the sink as we return the bridge term.
        from sugar_lift_py_tests.factory.literal_call_report import _floor_to_term, euf_call_term

        arg = complete_value(self.argument.reduce(ctx), owner="BridgeStrategy argument")
        # Only a CONCRETE arg can be dug (curried over a value); a symbolic formal -- the
        # universe build -- leaves the bridge symbolic and enqueues nothing.
        if not isinstance(arg, SymbolicValue):
            sink = getattr(ctx, "dig_sink", None)
            if sink is not None:
                sink.append((self.target_name, arg))
        return Complete(SymbolicValue(euf_call_term(self.target_name, [_floor_to_term(arg)])))

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
class ExternalBridgeStrategy:
    """An imported call whose Python body is absent.

    This is not a proof and not a local universe. It emits the same EUF call term the
    verifier/linker know how to compose later, and records a report edge saying which
    external source symbol must be supplied by another proof bundle.
    """

    target_name: str
    arguments: tuple[SugarBody, ...]
    keywords: tuple[tuple[str, SugarBody], ...]
    line: int
    column: int

    def __post_init__(self) -> None:
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("ExternalBridgeStrategy argument must be factory-built")
        for _name, value in self.keywords:
            if not isinstance(value, SugarBody):
                raise TypeError("ExternalBridgeStrategy keyword value must be factory-built")

    @property
    def target_symbol(self) -> str:
        return f"call:{self.target_name}"

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        terms = []
        for argument in self.arguments:
            value = complete_value(
                argument.reduce(ctx), owner="ExternalBridgeStrategy argument"
            )
            terms.append(floor_to_term(value, owner="external bridge argument"))
        for name, keyword in self.keywords:
            value = complete_value(
                keyword.reduce(ctx), owner=f"ExternalBridgeStrategy keyword {name}"
            )
            terms.append(
                ctor(
                    f"kw:{name}",
                    [floor_to_term(value, owner=f"external bridge keyword {name}")],
                )
            )
        sink = getattr(ctx, "external_bridge_sink", None)
        if sink is not None:
            sink.append(
                {
                    "targetSymbol": self.target_symbol,
                    "targetName": self.target_name,
                    "line": self.line,
                    "column": self.column,
                }
            )
        return Complete(SymbolicValue(euf_call_term(self.target_name, terms)))


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
        from dataclasses import replace

        from sugar_lift_py_tests.factory.sugar_constructors import build_bridge_body
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        import_target = fragment.call_import_target_name(
            getattr(ctx, "import_aliases", {}) or {},
            getattr(ctx, "from_imports", {}) or {},
        )
        bare_target = fragment.call_target_name()
        target = import_target or bare_target
        resolver = getattr(ctx, "name_resolver", None) or {}
        function_node = resolver.get(target)
        building = getattr(ctx, "building", frozenset())
        # RESOLVED + unary + NOT already on the build stack -> the bridge carries its universe.
        # The build-stack check is the recursion guard: eagerly building a callee already being
        # built loops forever, and an infinite recursion is not finitely constructible. So a
        # cycle refuses (clean, named) instead of hanging -- the bridge stays the vendor's axiom.
        if (
            function_node is not None
            and target is not None
            and target not in building
            and not fragment.call_has_keywords()
            and fragment.call_arg_count() == 1
        ):
            argument = ctx.build_body(fragment.call_args()[0], SugarRole.TERM)
            function = SourceFragment.from_node(function_node, ctx.filename)
            body = build_bridge_body(function, replace(ctx, building=building | {target}))
            return cls(strategy=BridgeStrategy(target_name=target, argument=argument, body=body))
        if import_target is not None and function_node is None:
            arguments = tuple(
                ctx.build_body(arg, SugarRole.TERM) for arg in fragment.call_args()
            )
            keywords = []
            for keyword in fragment.call_keywords():
                name = keyword.keyword_arg_name()
                if name is None:
                    info = FactoryGapInfo(
                        owner="python.factory",
                        blame=fragment.blame,
                        observed="Call",
                        requested="term",
                        fix=(
                            f"resolve call to '{target}' with explicit keyword names; "
                            "add **kwargs bridge sugar"
                        ),
                    )
                    return cls(strategy=RefuseStrategy(info))
                keywords.append((name, ctx.build_body(keyword.keyword_value(), SugarRole.TERM)))
            return cls(
                strategy=ExternalBridgeStrategy(
                    target_name=import_target,
                    arguments=arguments,
                    keywords=tuple(keywords),
                    line=fragment.line,
                    column=fragment.col,
                )
            )
        # Otherwise (unresolved, non-unary, or a recursion cycle): a clean, NAMED refusal --
        # never a silent lift, never a hang.
        info = FactoryGapInfo(
            owner="python.factory", blame=fragment.blame, observed="Call", requested="term",
            fix=f"resolve call to '{target}' (local body, imported .proof, or a sugar)",
        )
        return cls(strategy=RefuseStrategy(info))

    def desugar(self, ctx) -> Outcome:
        return self.strategy.emit(self, ctx)


@dataclass(frozen=True)
class AssertionFactStrategy:
    """The SWORN FACT -- the vendor/test swearing 'it does this'. ``callee(args) == expected``
    lifts to ``eq(call:callee(args), expected)``, contract-named ``<callee>#euf#...::assertion``.
    The factory picks this strategy when it is FACT-seeking (an assertion subject), as opposed
    to BridgeStrategy (universe-seeking, an in-body callsite). Both keys come from the ONE
    canonical speller (euf_call_term / euf_callsite_name), so the fact's #euf# join is
    byte-canonical -- the same name a vendor's proof emits for the same call."""

    callee_name: str
    arg_terms: tuple
    expected_term: object

    def _euf_term(self):
        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        return euf_call_term(self.callee_name, list(self.arg_terms))

    def contract_name(self) -> str:
        from sugar_lift_py_tests.factory.literal_call_report import euf_callsite_name

        return euf_callsite_name(self.callee_name, self._euf_term(), suffix="::assertion")

    def fact_formula(self):
        return eq(self._euf_term(), self.expected_term)

    def emit(self, sugar, ctx) -> Outcome:
        # The assertion subject, reduced as a term, IS the bridge `call:callee(args)`.
        return Complete(SymbolicValue(self._euf_term()))
