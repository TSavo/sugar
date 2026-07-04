from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Protocol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import FactoryGapEffect
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.factory.factory_gap_info import (
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.ir import Formula, Term, eq, make_var, str_const
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    SugarWitnessPair,
    SugarWitnesses,
    WitnessSource,
)
from sugar_lift_py_tests.sugar_body import SugarBody

# A resolved callee's body is either a single TERM expression (`return <expr>`, a
# SugarBody) or a multi-statement universe (control flow / encoder, a FunctionBodyUniverse).
FunctionCallBody = SugarBody | FunctionBodyUniverse
_BODY_TYPES = (SugarBody, FunctionBodyUniverse)


class CallStrategy(Protocol):
    def emit(self, sugar: "CallSugar", ctx: object) -> Outcome: ...


@dataclass(frozen=True)
class TypedEffectStrategy:
    incomplete: Incomplete

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        del sugar, ctx
        return self.incomplete


@dataclass(frozen=True)
class RefuseStrategy:
    """Nothing resolves this call -- a clean, NAMED refusal (a FactoryGap), built where the
    fragment's blame lives and raised on reduce. A refusal is sound: it says exactly what is
    missing (a body, an imported `.proof`, or a sugar), never a silent lift, never a side door.
    """

    info: FactoryGapInfo

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        audit = FactoryAuditRow(
            role="term",
            status="refused",
            observed=self.info.observed,
            blame=self.info.blame,
            selected="CallSugar",
            candidates=["CallSugar"],
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
    the catalog. The in-body bridge EMIT and the dig obligation are one construction act.)
    """

    target_name: str
    parameters: tuple[str, ...]
    arguments: tuple[SugarBody, ...]
    body: FunctionCallBody

    def __post_init__(self) -> None:
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("BridgeStrategy arguments must be factory-built")
        if not isinstance(self.body, _BODY_TYPES):
            raise TypeError("BridgeStrategy body must be factory-built")

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        # Emit the bridge AND enqueue its dig -- one act. `call:<callee>(arg)` is a POINTER to
        # the callee's tower; the instant we emit it, that tower is OWED a contract. A bridge
        # with nothing defining `call:<callee>(arg)` is a dangling free symbol the ground-
        # contradiction check cannot fold (a false discharge), so pointer and obligation are
        # inseparable: we append the dig to the sink as we return the bridge term.
        from sugar_lift_py_tests.factory.literal_call_report import (
            euf_call_term,
        )
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        arg_values = tuple(
            complete_value(argument.reduce(ctx), owner="BridgeStrategy argument")
            for argument in self.arguments
        )
        term = euf_call_term(
            self.target_name,
            [
                floor_to_term(arg, owner="bridge strategy argument")
                for arg in arg_values
            ],
        )
        call_value = CallSiteValue(
            target_name=self.target_name,
            arg_values=arg_values,
            parameters=self.parameters,
            term=term,
            body=self.body,
        )
        # Only concrete args can be dug (curried over values); symbolic formals leave
        # the bridge symbolic and enqueue nothing.
        if not any(
            isinstance(arg, (SymbolicValue, CallSiteValue)) for arg in arg_values
        ):
            sink = ctx.dig_sink
            if sink is not None:
                sink.append(call_value)
        return Complete(call_value)

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
        body = self.body
        if len(self.arguments) != 1:
            raise ValueError("BridgeStrategy callsite facts require one argument")
        argument = complete_value(
            self.arguments[0].reduce(None), owner="BridgeStrategy argument"
        )
        if not isinstance(argument, StringValue):
            raise ValueError("write more Floor for BridgeStrategy argument")
        return [
            eq(make_var(body.parameter), str_const(argument.value)),
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
                raise TypeError(
                    "ExternalBridgeStrategy keyword value must be factory-built"
                )

    @property
    def target_symbol(self) -> str:
        return f"call:{self.target_name}"

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        terms = []
        for argument in self.arguments:
            argument_outcome = argument.reduce(ctx)
            if isinstance(argument_outcome, Incomplete):
                return argument_outcome
            value = complete_value(
                argument_outcome, owner="ExternalBridgeStrategy argument"
            )
            terms.append(floor_to_term(value, owner="external bridge argument"))
        for name, keyword in self.keywords:
            keyword_outcome = keyword.reduce(ctx)
            if isinstance(keyword_outcome, Incomplete):
                return keyword_outcome
            value = complete_value(
                keyword_outcome, owner=f"ExternalBridgeStrategy keyword {name}"
            )
            terms.append(
                ctor(
                    f"kw:{name}",
                    [floor_to_term(value, owner=f"external bridge keyword {name}")],
                )
            )
        sink = ctx.external_bridge_sink
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
class MethodCallStrategy:
    method_name: str
    receiver: SugarBody
    arguments: tuple[SugarBody, ...]
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("MethodCallStrategy receiver must be factory-built")
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("MethodCallStrategy arguments must be factory-built")

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        del sugar
        from sugar_lift_py_tests.operations import (
            MethodCallOperation,
            perform_operation,
        )

        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(receiver_outcome, owner="MethodCallStrategy receiver")
        arguments = []
        for argument in self.arguments:
            argument_outcome = argument.reduce(ctx)
            if isinstance(argument_outcome, Incomplete):
                return argument_outcome
            arguments.append(
                complete_value(argument_outcome, owner="MethodCallStrategy argument")
            )
        operation = MethodCallOperation(
            name=self.method_name,
            arguments=tuple(arguments),
            owner="CallSugar",
            blame=self.blame,
        )
        return perform_operation(
            owner="CallSugar",
            blame=self.blame,
            receiver=receiver,
            operation=operation,
            ctx=ctx,
        )


@dataclass(frozen=True)
class ObjectCallStrategy:
    callee: SugarBody
    arguments: tuple[SugarBody, ...]
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.callee, SugarBody):
            raise TypeError("ObjectCallStrategy callee must be factory-built")
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("ObjectCallStrategy arguments must be factory-built")

    def emit(self, sugar: "CallSugar", ctx) -> Outcome:
        del sugar
        from sugar_lift_py_tests.operations import (
            MethodCallOperation,
            perform_operation,
        )

        callee = complete_value(
            self.callee.reduce(ctx), owner="ObjectCallStrategy callee"
        )
        arguments = tuple(
            complete_value(argument.reduce(ctx), owner="ObjectCallStrategy argument")
            for argument in self.arguments
        )
        operation = MethodCallOperation(
            name="__call__",
            arguments=arguments,
            owner="CallSugar",
            blame=self.blame,
        )
        return perform_operation(
            owner="CallSugar",
            blame=self.blame,
            receiver=callee,
            operation=operation,
            ctx=ctx,
        )


@dataclass(frozen=True)
class CallSugar(Sugar, role=SugarRole.TERM):
    """A call -- DUMB. `owns` is shape only; `build` is the ONLY place context decides (it
    picks the strategy by resolution); `desugar` is one line, delegating. Every Call-owning
    sugar declares `comes_before=("CallSugar",)`, so CallSugar is the fallback catching every
    call no specific sugar claimed -- resolved (BridgeStrategy) or not (RefuseStrategy).
    """

    strategy: CallStrategy

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Call"

    @classmethod
    def witnesses(cls) -> SugarWitnesses:
        def pair(
            name: str,
            family: str,
            prefix: str,
            expression: str,
            truthful: str,
            lying: str,
        ) -> SugarWitnessPair:
            return SugarWitnessPair(
                name=name,
                owner_sugar=cls.__name__,
                family=family,
                truthful=WitnessSource(
                    source=(
                        f"{prefix}"
                        "def A():\n"
                        f"    return {expression}\n"
                        "\n"
                        "def test_a():\n"
                        f"    assert A() == {truthful}\n"
                    ),
                    expected="sat",
                ),
                lying=WitnessSource(
                    source=(
                        f"{prefix}"
                        "def A():\n"
                        f"    return {expression}\n"
                        "\n"
                        "def test_a():\n"
                        f"    assert A() == {lying}\n"
                    ),
                    expected="unsat",
                ),
            )

        return (
            pair(
                "slice_callsite",
                "slice/subscript",
                "",
                "'abcdef'[1:3]",
                "'bc'",
                "'zz'",
            ),
            pair(
                "binary_dunder_callsite",
                "binary-dunder",
                (
                    "class X:\n"
                    "    def __init__(self, y):\n"
                    "        self.x = y\n"
                    "    def __add__(self, other):\n"
                    "        return other.x\n"
                    "\n"
                ),
                "[10, 20, 30][X(0) + X(1)]",
                "20",
                "10",
            ),
            pair(
                "object_next_callsite",
                "object-next-dunder",
                (
                    "class Box:\n"
                    "    def __init__(self, x):\n"
                    "        self.x = x\n"
                    "    def __next__(self):\n"
                    "        return self.x\n"
                    "\n"
                ),
                "[10, 20, 30][next(Box(1))]",
                "20",
                "10",
            ),
            pair(
                "object_getitem_callsite",
                "object-getitem-dunder",
                (
                    "class Box:\n"
                    "    def __init__(self, x):\n"
                    "        self.x = x\n"
                    "    def __getitem__(self, key):\n"
                    "        return self.x\n"
                    "\n"
                ),
                "[10, 20, 30][Box(1)[0]]",
                "20",
                "10",
            ),
            pair(
                "object_call_slot_callsite",
                "object-call-slot",
                (
                    "class CallableReturningOne:\n"
                    "    def __call__(self):\n"
                    "        return 1\n"
                    "\n"
                ),
                "[10, 20, 30][CallableReturningOne()()]",
                "20",
                "10",
            ),
            pair(
                "object_display_conversion_callsite",
                "object-display-conversion-dunder",
                (
                    "class Box:\n"
                    "    def __repr__(self):\n"
                    "        return 'one'\n"
                    "\n"
                ),
                "[10, 20, 30][repr(Box()) == 'one']",
                "20",
                "10",
            ),
            pair(
                "object_rich_compare_callsite",
                "object-rich-comparison-dunder",
                (
                    "class X:\n"
                    "    def __init__(self, x):\n"
                    "        self.x = x\n"
                    "    def __lt__(self, other):\n"
                    "        return other.x\n"
                    "\n"
                ),
                "[10, 20, 30][X(0) < X(1)]",
                "20",
                "10",
            ),
            pair(
                "builtin_len_callsite",
                "builtin-dunder-len",
                ("class Box:\n" "    def __len__(self):\n" "        return 1\n" "\n"),
                "[10, 20, 30][len(Box())]",
                "20",
                "10",
            ),
            pair(
                "builtin_hash_callsite",
                "builtin-dunder-hash",
                ("class Box:\n" "    def __hash__(self):\n" "        return 1\n" "\n"),
                "[10, 20, 30][hash(Box())]",
                "20",
                "10",
            ),
            pair(
                "builtin_divmod_callsite",
                "builtin-dunder-divmod",
                (
                    "class Box:\n"
                    "    def __init__(self, x):\n"
                    "        self.x = x\n"
                    "    def __divmod__(self, other):\n"
                    "        return self.x\n"
                    "\n"
                ),
                "[10, 20, 30][divmod(Box(1), 2)]",
                "20",
                "10",
            ),
        )

    @classmethod
    def build(cls, fragment, ctx) -> "CallSugar":
        from dataclasses import replace

        from sugar_lift_py_tests.factory.sugar_constructors import (
            IncompleteFunctionBody,
            build_bridge_body,
        )
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        import_target = fragment.call_import_target_name(
            ctx.import_aliases or {},
            ctx.from_imports or {},
        )
        bare_target = fragment.call_target_name()
        target = import_target or bare_target
        resolver = ctx.name_resolver or {}
        function_node = resolver.get(target)
        building = ctx.building
        if function_node is not None and target is not None:
            resolved = SourceFragment.from_node(function_node, ctx.filename)
            if resolved.observed == "ClassDef":
                return cls(
                    strategy=_build_constructor_strategy(
                        fragment, ctx, target, resolved
                    )
                )
        if import_target is not None and _is_nested_import_target(import_target):
            return cls(
                strategy=_build_external_bridge_strategy(
                    fragment, ctx, import_target, target
                )
            )
        # RESOLVED + unary + NOT already on the build stack -> the bridge carries its universe.
        # The build-stack check is the recursion guard: eagerly building a callee already being
        # built loops forever, and an infinite recursion is not finitely constructible. So a
        # cycle refuses (clean, named) instead of hanging -- the bridge stays the vendor's axiom.
        if (
            function_node is not None
            and target is not None
            and target not in building
            and not fragment.call_has_keywords()
            and fragment.call_arg_count() in {0, 1}
        ):
            function = SourceFragment.from_node(function_node, ctx.filename)
            parameters = tuple(function.function_params())
            if len(parameters) != fragment.call_arg_count():
                return cls(
                    strategy=RefuseStrategy(
                        FactoryGapInfo(
                            owner="python.factory",
                            blame=fragment.blame,
                            observed=f"{target}(...)",
                            requested=f"{len(parameters)} call arguments",
                            fix=f"add argument binding sugar for `{target}`",
                        )
                    )
                )
            arguments = tuple(
                ctx.build_body(arg, SugarRole.TERM) for arg in fragment.call_args()
            )
            try:
                body = build_bridge_body(
                    function, replace(ctx, building=building | {target})
                )
            except IncompleteFunctionBody as exc:
                return cls(strategy=TypedEffectStrategy(exc.incomplete))
            except TypeError as exc:
                return cls(
                    strategy=RefuseStrategy(
                        FactoryGapInfo(
                            owner="python.factory",
                            blame=function.blame,
                            observed=f"call-local:{target}",
                            requested="FunctionBodyConstraint",
                            fix=(
                                f"lift this function body for `{target}` "
                                f"or emit a real effect: {exc}"
                            ),
                        )
                    )
                )
            return cls(
                strategy=BridgeStrategy(
                    target_name=target,
                    parameters=parameters,
                    arguments=arguments,
                    body=body,
                )
            )
        if import_target is not None and function_node is None:
            return cls(
                strategy=_build_external_bridge_strategy(
                    fragment, ctx, import_target, target
                )
            )
        if (
            fragment.call_is_method_call()
            and target is not None
            and (
                _resolver_has_method(ctx, target)
                or _method_receiver_is_temporally_bound(fragment, ctx)
            )
        ):
            receiver = fragment.call_receiver()
            if receiver is not None:
                return cls(
                    strategy=MethodCallStrategy(
                        method_name=target,
                        receiver=ctx.build_body(receiver, SugarRole.TERM),
                        arguments=tuple(
                            ctx.build_body(arg, SugarRole.TERM)
                            for arg in fragment.call_args()
                        ),
                        blame=fragment.blame,
                    )
                )
        if target is None and not fragment.call_has_keywords():
            return cls(
                strategy=ObjectCallStrategy(
                    callee=ctx.build_body(fragment.call_func(), SugarRole.TERM),
                    arguments=tuple(
                        ctx.build_body(arg, SugarRole.TERM)
                        for arg in fragment.call_args()
                    ),
                    blame=fragment.blame,
                )
            )
        # Otherwise (unresolved, non-unary, or a recursion cycle): a clean, NAMED refusal --
        # never a silent lift, never a hang.
        observed = _call_frontier_observed(
            fragment, import_target=import_target, target=target
        )
        info = FactoryGapInfo(
            owner="python.factory",
            blame=fragment.blame,
            observed=observed,
            requested="term",
            fix=_call_frontier_fix(
                fragment, import_target=import_target, target=target
            ),
        )
        return cls(strategy=RefuseStrategy(info))

    def desugar(self, ctx) -> Outcome:
        return self.strategy.emit(self, ctx)


def _method_receiver_is_temporally_bound(fragment, ctx) -> bool:
    if fragment.call_has_keywords():
        return False
    receiver = fragment.call_receiver()
    if receiver is None or receiver.observed != "Name":
        return False
    receiver_name = receiver.name_id()
    return any(binding.name == receiver_name for binding in ctx.temporal.bindings)


def _build_constructor_strategy(fragment, ctx, target: str, class_site):
    from sugar_lift_py_tests.sugar.constructor_strategy import ConstructorStrategy

    if fragment.call_has_keywords():
        return RefuseStrategy(
            FactoryGapInfo(
                owner="python.factory",
                blame=fragment.blame,
                observed=f"{target}(...)",
                requested="positional constructor arguments",
                fix=f"add keyword constructor argument binding sugar for `{target}`",
                gap_kind=GapKind.CONSTRUCTOR,
            )
        )
    methods = _build_object_methods(class_site, ctx)
    init = _find_init(class_site)
    if init is None:
        if fragment.call_arg_count() != 0:
            if _has_opaque_constructor_base(class_site, ctx):
                return TypedEffectStrategy(
                    Incomplete(
                        FactoryGapEffect(
                            owner="python.factory",
                            blame=fragment.blame,
                            observed=f"{target}(...)",
                            requested="inherited opaque constructor effect",
                            fix=(
                                f"link or prove constructor semantics for `{target}`'s "
                                "base class; do not fabricate a local __init__"
                            ),
                            gap_kind="Constructor",
                            gap_locus="AST",
                        )
                    )
                )
            return RefuseStrategy(
                FactoryGapInfo(
                    owner="python.factory",
                    blame=fragment.blame,
                    observed=f"{target}(...)",
                    requested="zero-arg constructor",
                    fix=f"add constructor argument binding sugar for `{target}`",
                    gap_kind=GapKind.CONSTRUCTOR,
                )
            )
        return ConstructorStrategy(
            class_name=target,
            fields=(),
            methods=methods,
            class_fields=_build_class_fields(class_site, ctx),
            identity=fragment.blame,
        )
    params = init.function_params()
    if len(params) < 1:
        return RefuseStrategy(
            FactoryGapInfo(
                owner="python.factory",
                blame=init.blame,
                observed=f"{target}.__init__({', '.join(params)})",
                requested="constructor self parameter",
                fix=f"add constructor argument binding sugar for `{target}.__init__`",
                gap_kind=GapKind.CONSTRUCTOR,
            )
        )
    constructor_params = tuple(params[1:])
    if len(constructor_params) != fragment.call_arg_count():
        return RefuseStrategy(
            FactoryGapInfo(
                owner="python.factory",
                blame=fragment.blame,
                observed=f"{target}(...)",
                requested=f"{len(constructor_params)} constructor arguments",
                fix=f"add constructor argument binding sugar for `{target}`",
                gap_kind=GapKind.CONSTRUCTOR,
            )
        )
    self_name = params[0]
    fields: list[tuple[str, SugarBody]] = []
    for stmt in init.function_body():
        if _is_inert_constructor_statement(stmt):
            continue
        if (
            stmt.observed == "Assign"
            and stmt.assign_target_attribute_receiver_name() == self_name
            and stmt.assign_target_attribute_name() is not None
        ):
            fields.append(
                (
                    stmt.assign_target_attribute_name(),
                    ctx.build_body(stmt.assign_value(), SugarRole.TERM),
                )
            )
            continue
        return RefuseStrategy(
            FactoryGapInfo(
                owner="python.factory",
                blame=stmt.blame,
                observed=f"{target}.__init__:{stmt.observed}",
                requested="constructor field assignment",
                fix=(
                    f"write more constructor sugar for `{target}.__init__`: "
                    "support this statement shape or emit an effect"
                ),
                gap_kind=GapKind.CONSTRUCTOR,
            )
        )
    return ConstructorStrategy(
        class_name=target,
        fields=tuple(fields),
        parameters=constructor_params,
        arguments=tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in fragment.call_args()
        ),
        methods=methods,
        class_fields=_build_class_fields(class_site, ctx),
        identity=fragment.blame,
    )


def _has_opaque_constructor_base(class_site, ctx) -> bool:
    base_names = class_site.class_base_names()
    if not base_names:
        return False
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    for base_name in base_names:
        if base_name is not None:
            resolved = ctx.name_resolver.get(base_name)
            if resolved is not None:
                base_site = SourceFragment.from_node(resolved, ctx.filename)
                if base_site.observed == "ClassDef":
                    continue
        return True
    return False


def _build_class_fields(class_site, ctx):
    fields = []
    for stmt in class_site.class_body():
        if stmt.observed != "Assign":
            continue
        name = stmt.assign_target_name()
        if name is None:
            continue
        value = stmt.assign_value()
        if not (
            _is_resolved_local_class_call(value, ctx)
            or _is_external_bridge_call(value, ctx)
        ):
            continue
        fields.append((name, ctx.build_body(value, SugarRole.TERM)))
    return tuple(fields)


def _is_external_bridge_call(fragment, ctx) -> bool:
    if fragment.observed != "Call":
        return False
    return (
        fragment.call_import_target_name(ctx.import_aliases or {}, ctx.from_imports or {})
        is not None
    )


def _is_resolved_local_class_call(fragment, ctx) -> bool:
    if fragment.observed != "Call":
        return False
    target = (
        fragment.call_import_target_name(
            ctx.import_aliases or {},
            ctx.from_imports or {},
        )
        or fragment.call_target_name()
    )
    resolver = ctx.name_resolver or {}
    resolved_node = resolver.get(target)
    if resolved_node is None:
        return False
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    return SourceFragment.from_node(resolved_node, ctx.filename).observed == "ClassDef"


def _is_nested_import_target(import_target: str) -> bool:
    return import_target.count(".") >= 2


def _build_external_bridge_strategy(
    fragment, ctx, import_target: str, target: str | None
):
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
                observed=_call_frontier_observed(
                    fragment, import_target=import_target, target=target
                ),
                requested="term",
                fix=(
                    f"resolve call to '{target}' with explicit keyword names; "
                    "add **kwargs bridge sugar"
                ),
            )
            return RefuseStrategy(info)
        keywords.append((name, ctx.build_body(keyword.keyword_value(), SugarRole.TERM)))
    return ExternalBridgeStrategy(
        target_name=import_target,
        arguments=arguments,
        keywords=tuple(keywords),
        line=fragment.line,
        column=fragment.col,
    )


def _build_object_methods(class_site, ctx):
    from sugar_lift_py_tests.floor import ObjectMethodValue

    methods = []
    for stmt in class_site.class_body():
        if stmt.observed != "FunctionDef" or stmt.function_name() == "__init__":
            continue
        body = stmt.function_body()
        if (
            len(body) == 1
            and body[0].observed == "Return"
            and body[0].return_value() is not None
        ):
            methods.append(
                ObjectMethodValue(
                    name=stmt.function_name(),
                    parameters=tuple(stmt.function_params()),
                    body=ctx.build_body(body[0].return_value(), SugarRole.TERM),
                )
            )
    return tuple(methods)


def _resolver_has_method(ctx, method_name: str) -> bool:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    resolver = ctx.name_resolver or {}
    for node in resolver.values():
        site = SourceFragment.from_node(node, ctx.filename)
        if site.observed != "ClassDef":
            continue
        for stmt in site.class_body():
            if stmt.observed == "FunctionDef" and stmt.function_name() == method_name:
                return True
    return False


def _find_init(class_site):
    for stmt in class_site.class_body():
        if stmt.observed == "FunctionDef" and stmt.function_name() == "__init__":
            return stmt
    return None


def _is_inert_constructor_statement(stmt) -> bool:
    return (
        stmt.observed == "Expr"
        and stmt.expr_value().observed == "PrimitiveLiteral"
        and isinstance(stmt.expr_value().literal_value(), str)
    )


def _call_frontier_observed(fragment, *, import_target: str | None, target: str | None):
    label = (
        import_target or fragment.call_qualified_target_name() or target or "unknown"
    )
    if import_target is not None:
        return f"call-external:{label}"
    if target in _BUILTIN_CALLS:
        return f"call-builtin:{target}"
    if fragment.call_is_method_call():
        return f"call-method:{target or label}"
    return f"call-local:{target or label}"


def _call_frontier_fix(
    fragment, *, import_target: str | None, target: str | None
) -> str:
    label = (
        import_target or fragment.call_qualified_target_name() or target or "unknown"
    )
    if import_target is not None:
        return (
            f"link external call `{label}` to an imported .proof, add sugar, "
            "or emit a real effect"
        )
    if target in _BUILTIN_CALLS:
        return (
            f"add builtin call sugar for `{target}`, resolve a local body, "
            "link an imported .proof, or emit a real effect"
        )
    if fragment.call_is_method_call():
        return (
            f"add receiver-dispatched method sugar for `{target or label}`, "
            "resolve a local body, link an imported .proof, or emit a real effect"
        )
    return (
        f"resolve local call `{target or label}` to a body, link an imported .proof, "
        "add sugar, or emit a real effect"
    )


_BUILTIN_CALLS = frozenset(dir(builtins))


@dataclass(frozen=True)
class AssertionFactStrategy:
    """The SWORN FACT -- the vendor/test swearing 'it does this'. ``callee(args) == expected``
    lifts to ``eq(call:callee(args), expected)``, contract-named ``<callee>#euf#...::assertion``.
    The factory picks this strategy when it is FACT-seeking (an assertion subject), as opposed
    to BridgeStrategy (universe-seeking, an in-body callsite). Both keys come from the ONE
    canonical speller (euf_call_term / euf_callsite_name), so the fact's #euf# join is
    byte-canonical -- the same name a vendor's proof emits for the same call."""

    callee_name: str
    arg_terms: tuple[Term, ...]
    expected_term: Term

    def _euf_term(self) -> Term:
        from sugar_lift_py_tests.factory.literal_call_report import euf_call_term

        return euf_call_term(self.callee_name, list(self.arg_terms))

    def contract_name(self) -> str:
        from sugar_lift_py_tests.factory.literal_call_report import euf_callsite_name

        return euf_callsite_name(
            self.callee_name, self._euf_term(), suffix="::assertion"
        )

    def fact_formula(self) -> Formula:
        return eq(self._euf_term(), self.expected_term)

    def emit(self, sugar, ctx) -> Outcome:
        # The assertion subject, reduced as a term, IS the bridge `call:callee(args)`.
        return Complete(SymbolicValue(self._euf_term()))
