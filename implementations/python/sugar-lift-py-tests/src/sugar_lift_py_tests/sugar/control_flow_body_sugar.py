from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, and_, eq, implies, make_var
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ControlFlowBodySugar(
    Sugar, FunctionBodyUniverse, role=SugarRole.CONTROL_FLOW_BODY
):
    """A function body with branching returns, lifted as guarded implications.

    Control flow is NOT executed -- it becomes first-order logic. Each return path
    is `(guard, out == return-term)`, where the guard is the conjunction of the
    `if` conditions on the way to that return (the `else` branch negates the test).
    The body's universe is the conjunction of those implications:

        (k == 2)          -> out == ...
        (k != 2 & k == 1) -> out == ...
        (k != 2 & k != 1) -> out == ...

    z3 does the branching for free: given the bound inputs, the guards resolve and
    the active path's `out == ...` is the live constraint. A single unguarded path
    collapses to a plain equality (straight-line bodies are the degenerate case). The
    per-line walk is inherited.

    Construction is eager: ``new`` builds the Block child through the factory,
    reduces it, and materializes path/opaque coordinates. That is the deletion of
    the factory-side body reduction side door (#5205) — Sugar owns the reduce and
    floor projection; the factory only selects this claim.
    """

    parameter: str
    # each path: (tuple of guard Formulas, the return-value Term)
    paths: tuple[tuple[tuple[Formula, ...], Term], ...]
    formals: tuple[str, ...]
    statements: tuple[SugarBody, ...] = ()
    # OpaqueOpCallsite return floors from the body walk (PR #3900 A / #3906).
    # Path post is always `out == call:<op>(...)` for both foldable and opaque
    # returns. Counted returns (`computed is not None`) also mint a Derived
    # companion `call:len(...) == N` at universe mint; opaque returns
    # (`computed is None`, e.g. hash) get the universe post only — the sworn
    # assertion grounds the coordinate via the shared call:A() euf key.
    opaque_returns: tuple[object, ...] = ()

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "FunctionDef"

    @classmethod
    def new(cls, site, ctx) -> "ControlFlowBodySugar":
        """Select-time construction: factory-built Block + Sugar-owned reduction.

        Encoder bodies are a specialized FunctionBodyUniverse; ``new`` still
        returns this claim so catalog typing stays closed. Dig callers use
        ``select_control_flow_body_sugar``, which rewrites the encoder special
        case to ``EncoderBodySugar`` after selection.
        """
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            BlockValue,
            EncodedStringValue,
            GuardedReturn,
            OpaqueOpCallsite,
            ReturnValue,
        )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        if site.observed != "FunctionDef":
            raise TypeError("ControlFlowBodySugar claim built a non-function")

        params = tuple(site.function_params())
        body = ctx.build_body(site.function_body_block(), SugarRole.STATEMENT)
        statements = getattr(body.sugar, "statements", None)
        if not isinstance(statements, tuple):
            raise TypeError(
                "ControlFlowBodySugar requires a factory-built BlockSugar child"
            )

        block_outcome = body.reduce(ctx)
        if isinstance(block_outcome, Incomplete):
            factory_panic_gap(
                owner="ControlFlowBodySugar.new",
                blame=site,
                observed=site.observed,
                requested=SugarRole.CONTROL_FLOW_BODY.value,
                fix=(
                    "construct the body in its owning statement Sugars or narrow "
                    "ControlFlowBodySugar.owns so the factory None arm panics"
                ),
                selected=cls.__name__,
            )
        block_value = complete_value(block_outcome, owner="function body")
        if type(block_value) is not BlockValue:
            raise TypeError(
                "ControlFlowBodySugar expected BlockValue, got "
                f"{type(block_value).__name__}"
            )
        block_value = cast(BlockValue, block_value)
        outcomes = block_value.statements

        # Encoder special case is recognized here so dig can rewrite after
        # selection; paths stay empty and statements carry the composed body.
        if (
            len(outcomes) == 1
            and isinstance(outcomes[0], ReturnValue)
            and isinstance(outcomes[0].value, EncodedStringValue)
        ):
            if not params:
                raise TypeError("EncoderBodySugar requires at least one parameter")
            return cls(
                parameter=params[0],
                paths=(),
                formals=params,
                statements=statements,
                opaque_returns=(outcomes[0].value,),
            )

        paths: list[tuple[tuple[Formula, ...], Term]] = []
        opaque_returns: list[OpaqueOpCallsite] = []
        for outcome in outcomes:
            if isinstance(outcome, ReturnValue):
                ret_value = outcome.value
                paths.append(((), floor_to_term(ret_value, owner="control-flow body")))
            elif isinstance(outcome, GuardedReturn):
                ret_value = outcome.value
                paths.append(
                    (
                        tuple(outcome.guards),
                        floor_to_term(ret_value, owner="control-flow body"),
                    )
                )
            else:
                raise TypeError(
                    "control-flow body: unexpected outcome "
                    f"`{type(outcome).__name__}`"
                )
            if isinstance(ret_value, OpaqueOpCallsite):
                opaque_returns.append(ret_value)
        if not paths:
            raise TypeError("ControlFlowBodySugar found no return paths")
        return cls(
            parameter=params[0] if params else "",
            paths=tuple(paths),
            formals=params,
            statements=statements,
            opaque_returns=tuple(opaque_returns),
        )

    @classmethod
    def witnesses(cls):
        source = (
            "def choose(value):\n"
            "    if value == 7:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="control_flow_body_return_paths",
            owner_sugar="ControlFlowBodySugar",
            truthful=source + "def test_choose():\n    assert choose(7) == 1\n",
            lying=source + "def test_choose():\n    assert choose(7) == 0\n",
        )

    def _as_encoder_body(self):
        """Rewrite the encoder special case recognized in ``new``."""
        from sugar_lift_py_tests.floor import EncodedStringValue
        from sugar_lift_py_tests.sugar.encoder_body_sugar import EncoderBodySugar

        if self.paths:
            return None
        if len(self.opaque_returns) != 1:
            return None
        encoded = self.opaque_returns[0]
        if not isinstance(encoded, EncodedStringValue):
            return None
        if not self.formals:
            raise TypeError("EncoderBodySugar requires at least one parameter")
        return EncoderBodySugar(
            parameter=self.formals[0],
            encoded=encoded,
            statements=self.statements,
        )

    @staticmethod
    def build_context(site, ctx):
        """Bind a function's lexical module and symbolic formal coordinates."""
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
            StatementFunctionDefSugar,
        )
        from sugar_lift_py_tests.temporal import TemporalContext, bind_temporal

        module_temporal = getattr(ctx, "module_temporal", None)
        body_ctx = ctx.with_temporal(
            module_temporal if module_temporal is not None else TemporalContext()
        )
        body_ctx = StatementFunctionDefSugar.module_context_for(site, body_ctx)
        for param_name in site.function_params():
            body_ctx = bind_temporal(
                body_ctx,
                param_name,
                SymbolicValue(make_var(param_name)),
                owner="ControlFlowBodySugar.formal_binds",
                blame=f"{getattr(site, 'filename', '')}:{getattr(site, 'line', 0)}",
            )
        return body_ctx

    @staticmethod
    def build_bridge_body(site, ctx):
        """Build the exact single-return bridge through the registered term Sugar."""
        body_frags = site.function_body()
        if len(body_frags) != 1:
            raise TypeError("ControlFlowBodySugar bridge requires one statement")
        body_frag = body_frags[0]
        if body_frag.observed != "Return" or body_frag.return_value() is None:
            raise TypeError("ControlFlowBodySugar bridge requires a valued return")
        return ControlFlowBodySugar.build_context(site, ctx).build_body(
            body_frag.return_value(), SugarRole.TERM
        )

    def _clauses(self) -> list[Formula]:
        clauses: list[Formula] = []
        for guards, ret_term in self.paths:
            consequent = eq(make_var("out"), ret_term)
            if not guards:
                clauses.append(consequent)
            elif len(guards) == 1:
                clauses.append(implies(guards[0], consequent))
            else:
                clauses.append(implies(and_(list(guards)), consequent))
        return clauses

    def constraint_formulas(self) -> list[Formula]:
        encoder = self._as_encoder_body()
        if encoder is not None:
            return encoder.constraint_formulas()
        # Path clauses only — companions are separate Derived facts.
        clauses = self._clauses()
        return [clauses[0] if len(clauses) == 1 else and_(clauses)]

    def desugar(self, ctx: Any = None) -> Outcome:
        # Dig consumers read FunctionBodyUniverse posts; if the catalog wraps
        # this claim in SugarBody, replaying the already-selected statements
        # is the honest reduction (construction already lowered paths).
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

        return BlockSugar(
            statements=self.statements,
            blame="ControlFlowBodySugar",
        ).desugar(ctx)

    def walk_children(self):
        return self.statements


def select_control_flow_body_sugar(site, ctx) -> FunctionBodyUniverse:
    """Select the registered call-body Sugar through the ordinary factory door.

    Formal/module binding is owned by ``ControlFlowBodySugar`` (#5206).
    This selector supplies that Sugar-owned context, then lets the catalog build
    ``ControlFlowBodySugar``. Encoder bodies rewrite to ``EncoderBodySugar``
    after selection so dig consumers keep the prior FunctionBodyUniverse shape.
    """
    from sugar_lift_py_tests.factory.build import build_node

    body_ctx = ControlFlowBodySugar.build_context(site, ctx)
    result = build_node(
        site,
        filename=body_ctx.filename,
        role=SugarRole.CONTROL_FLOW_BODY,
        catalog=body_ctx.catalog,
        ctx=body_ctx,
    )
    sugar = result.sugar
    if not isinstance(sugar, ControlFlowBodySugar):
        raise TypeError(
            "control-flow body role selected "
            f"{type(sugar).__name__}, expected ControlFlowBodySugar"
        )
    encoder = sugar._as_encoder_body()
    if encoder is not None:
        return encoder
    return sugar
