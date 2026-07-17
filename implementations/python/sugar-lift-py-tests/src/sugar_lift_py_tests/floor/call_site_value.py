from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, NoReturn

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody

from .floor_value import FloorValue
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus

_FORCE_FLOOR_BUDGET = 64


@dataclass(frozen=True)
class ExitSuppressionContract:
    """Static evidence for one context manager's exceptional exit.

    An empty exception set proves propagation.  A non-empty set proves that
    exactly those named exception classes are suppressed.  Runtime-dependent
    exits carry no contract at all and therefore remain loud in WithSugar.
    """

    exception_names: frozenset[str]

    @classmethod
    def never_suppresses(cls) -> "ExitSuppressionContract":
        return cls(frozenset())

    @classmethod
    def suppresses(cls, exception_names: tuple[str, ...]) -> "ExitSuppressionContract":
        if not exception_names:
            raise ValueError("a suppressing exit contract must name an exception")
        return cls(frozenset(exception_names))

    def suppresses_exception(self, exception_name: str) -> bool:
        return exception_name in self.exception_names


@dataclass(frozen=True)
class CallSiteValue(FloorValue):
    """A callsite as two things at once.

    The `term` is the bridge/culture coordinate used by contract composition.
    The factory-built `body` is only reduced when a downstream floor demands a
    concrete value (for example, a list literal index). `site` is the fragment
    that owned the call -- carried for edge projection, never compared.
    """

    target_name: str
    arg_values: tuple[FloorValue, ...]
    parameters: tuple[str, ...]
    term: Term
    # Any is the open membrane here, matching FactoryBuildResult.sugar and
    # ObjectMethodValue.body: a callsite's factory-built body varies in
    # reduction shape with the SugarRole it was built under.
    body: SugarBody[Any] | FunctionBodyUniverse | None
    site: object = dataclass_field(default=None, compare=False)
    # A callee contract may cite the Python type object returned by this call.
    # Absent that citation, Python must execute the call to know whether its
    # result is a valid isinstance type operand.
    python_type_coordinate: Term | None = dataclass_field(default=None, compare=False)
    # Source-authenticated context-manager evidence.  None means undecidable,
    # never "does not suppress".
    exit_suppression: ExitSuppressionContract | None = None

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def truth(self, site):
        # A callsite EMITS py.truthy over its term, carrying itself as an operand.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(py_truthy(self.term), site, operand_callsites=(self,))
        )

    def bitwise_invert(self, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.term).bitwise_invert(site)

    def unary_minus(self, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.term).unary_minus(site)

    def absolute(self, site):
        """Cite ``abs(call(...))`` without claiming the call's concrete value."""
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.term).absolute(site)

    def test_python_type(self, value, site):
        type_coordinate = self.python_type_coordinate
        if type_coordinate is None and self.target_name == "type":
            type_coordinate = self.term
        if type_coordinate is None:
            from sugar_lift_py_tests.effect import (
                CallResultTypeRuntimeEffect,
                runtime_effect_witness,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
                CallResultTypeRuntimeEffect(
                    "call-result type runtime boundary: "
                    f"`{self.target_name}(...)` has no cited return-type/native "
                    "tester coordinate; Python must execute the call before its "
                    f"result can serve as an isinstance type operand; site={site}",
                    witness=runtime_effect_witness("adt.is_python_type", self, site),
                )
            )
        from sugar_lift_py_tests.floor.type_tester import native_type_tester

        return native_type_tester(
            value,
            type_coordinate,
            site,
            type_callsites=(self,),
        )

    def length(self, site):
        # A callsite length stays the call:len coordinate over this value's term.
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    "call:len",
                    [self.to_term(owner=str(site))],
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )

    def subscript(self, index, site):
        # A callsite receiver stays the py.subscript coordinate regardless of index.
        return self.py_subscript_coordinate(index, site)

    def setitem(self, index, value, site):
        """Record a store into an opaque call result as a typed runtime effect.

        The call, index, and value coordinates are known, but Python owns the
        mutated post-state. Preserve those coordinates in the effect fact and
        never fabricate a replacement receiver.
        """
        from sugar_lift_py_tests.effect import (
            SubscriptStoreRuntimeEffect,
            runtime_effect_witness,
        )
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        index_term = floor_to_term(index, owner="CallSiteValue.setitem index")
        value_term = floor_to_term(value, owner="CallSiteValue.setitem value")

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "subscript assignment runtime boundary: callsite receiver "
                f"`{self.term!r}` may invoke __setitem__; "
                f"index={index_term!r} value={value_term!r}; site={site}",
                witness=runtime_effect_witness("py.setitem", index_term, site),
            )
        )

    def append_with(self, value, site):
        """Rebind an opaque list-shaped callsite after ``.append(v)``.

        Concrete ``ListValue`` folds element history. A callsite (for example
        ``s.split(".")[:3]``) has no element history to fold, but the append
        statement still rebinds the name: carry the prior list coordinate and
        the appended value on ``py.list_append`` so later statements keep a
        FloorValue. Do not invent members; the coordinate is the post-state.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        value_term = floor_to_term(value, owner="CallSiteValue.append_with value")
        return Complete(
            CallSiteValue(
                target_name="list.append",
                arg_values=(self, value),
                parameters=(),
                term=ctor(
                    "py.list_append",
                    [self.to_term(owner=str(site)), value_term],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

    def callsites(self):
        # A CallSiteValue carries itself -- equals emit collects it so the
        # inv that consumes the term can still project the edge later.
        return (self,)

    def derived_equality_residue(self, ctx):
        """Return the callsite's ground body fact when its dig warrants one.

        The function universe already owns the body post.  Equality testimony
        additionally needs the callsite-keyed residue so the stated assertion
        and the derived value remain independently visible at the EUF join.
        Only a single ``out = literal`` post is a derived value pin; opaque,
        effectful, symbolic, and multi-exit bodies stay absent and therefore
        loud at the existing refusal/gap boundary.
        """
        floor = self._dig_floor_or_none(
            ctx,
            owner="CallSiteValue.derived_equality_residue",
        )
        if floor is None:
            return None
        posts = tuple(floor.post_contribution())

        from sugar_lift_py_tests.ir import (
            _Atomic,
            _ConstBool,
            _ConstInt,
            _ConstReal,
            _ConstStr,
            _Var,
            eq,
        )

        literal_types = (_ConstBool, _ConstInt, _ConstReal, _ConstStr)
        if not posts:
            rhs = floor.to_term(owner="CallSiteValue.derived_equality_residue")
        elif len(posts) == 1:
            post = posts[0]
            if not (
                isinstance(post, _Atomic)
                and post.name == "="
                and len(post.args) == 2
                and isinstance(post.args[0], _Var)
                and post.args[0].name == "out"
            ):
                return None
            rhs = post.args[1]
        else:
            return None
        if not isinstance(rhs, literal_types):
            return None
        return eq(self.term, rhs)

    def linear_method_call(self, method_name: str, args: tuple, site):
        """Name the next link in a timeless receiver-method rewrite."""
        from sugar_lift_py_tests.ir import ctor

        return CallSiteValue(
            target_name=method_name,
            arg_values=(self, *args),
            parameters=(),
            term=ctor(
                f"call:{method_name}",
                [
                    self.to_term(owner=str(site)),
                    *(arg.to_term(owner=str(site)) for arg in args),
                ],
                symbol_kind="method-coordinate",
            ),
            body=None,
            site=site,
        )

    def add(self, other, site):
        """Addition floor via interface dispatch: dig then redispatch, else EUF +.

        AddOpSugar calls left.add(right) — not binary_operator_with. Without this
        totalizer, dig of `want_bytes(x) + self.sep` factory_panics mid-body.
        """
        return self._dig_or_symbolic_binop(other, site, op="+", floor_method="add")

    def subtract(self, other, site):
        return self._dig_or_symbolic_binop(other, site, op="-", floor_method="subtract")

    def multiply(self, other, site):
        return self._dig_or_symbolic_binop(other, site, op="*", floor_method="multiply")

    def divide(self, other, site):
        return self._dig_or_symbolic_binop(other, site, op="/", floor_method="divide")

    def modulo(self, other, site):
        return self._dig_or_symbolic_binop(other, site, op="%", floor_method="modulo")

    def floor_divide(self, other, site):
        return self._dig_or_symbolic_binop(
            other, site, op="//", floor_method="floor_divide"
        )

    def left_shift(self, other, site):
        return self._dig_or_symbolic_binop(
            other, site, op="<<", floor_method="left_shift"
        )

    def right_shift(self, other, site):
        # Base64 / alphabet index math: `ord(c) >> 2` on call results.
        # Without this, FloorValue.right_shift panics (A2 mint-failed on
        # python-literal-base64 / base64-federation).
        return self._dig_or_symbolic_binop(
            other, site, op=">>", floor_method="right_shift"
        )

    def bitwise_and(self, other, site):
        # Same family as left_shift / bitwise_or: dig then redispatch, else
        # EUF `&`. Base20 / base64 nibble masks (`b0 & 15`) hit CallSiteValue.
        return self._dig_or_symbolic_binop(
            other, site, op="&", floor_method="bitwise_and"
        )

    def bitwise_or(self, other, site):
        return self._dig_or_symbolic_binop(
            other, site, op="|", floor_method="bitwise_or"
        )

    def matrix_multiply(self, other, site):
        return self._dig_or_symbolic_binop(
            other, site, op="@", floor_method="matrix_multiply"
        )

    def _dig_or_symbolic_binop(self, other, site, *, op: str, floor_method: str):
        """Dig body when present; redispatch op on dug floor; else SymbolicValue join.

        No invent of concrete sums. Ctx is None-tolerant (add(site) has no ctx).
        Mid-dig FactoryPanic → treat as opaque (same as dig_floor soft path).
        """
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        if isinstance(other, GuardedValue):
            return other.map_from_left(floor_method, self, site)

        dug = self._dig_floor_or_none(
            None,
            owner=f"CallSiteValue.{floor_method}",
        )
        if dug is not None and dug is not self:
            method = getattr(dug, floor_method, None)
            if callable(method):
                return method(other, site)

        return Complete(
            SymbolicValue(
                ctor(
                    op,
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def edge_contribution(self, source_contract):
        # Project one call-edge row: the coordinates this value already carries.
        # Seal/link fields (targetContract, cids) stay absent -- never faked.
        edge = {
            "kind": "call-edge",
            "sourceContract": source_contract,
            "targetSymbol": f"call:{self.target_name}",
        }
        if self.site is not None:
            edge["callSiteLocus"] = {
                "file": self.site.filename,
                "line": self.site.line,
                "col": self.site.col,
            }
            edge["callsite"] = str(self.site)
        return (edge,)

    def project_callsite_with(self, operation, ctx):
        return operation.project_callsite(self, ctx)

    def attribute_with(self, operation: Any, ctx: Any):
        del ctx
        from sugar_lift_py_tests.effect import (
            GetattrRuntimeEffect,
            runtime_effect_witness,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            GetattrRuntimeEffect(
                "callsite attribute runtime boundary: "
                f"`{self.target_name}.{operation.name}` requires executing the "
                "call result before Python attribute lookup; keep as typed red "
                "until a narrower vendor-cited floor owns the call result and "
                f"attribute. blame={operation.blame}",
                witness=runtime_effect_witness(
                    "py.getattr", operation.name, operation.blame
                ),
            )
        )

    def unary_operator_with(self, operation, ctx):
        from sugar_lift_py_tests.operations import perform_operation

        # No-recognizer force_floor panics (process-terminal). Do not catch.
        floor = force_floor(
            self,
            ctx,
            owner=f"{operation.owner} callsite unary operand",
            project_callsite=False,
        )
        return perform_operation(
            owner=operation.owner,
            blame=operation.blame,
            receiver=floor,
            operation=operation,
            ctx=ctx,
        )

    def binary_operator_with(self, operation, ctx):
        """Binary op on a callsite result (e.g. ``(x + y).substitute(...)``).

        Lift-probe residual: FactoryGap · observed=CallSiteValue ·
        requested=binary_operator_with. Mechanism: missing floor totalizer
        (sibling of unary_operator_with) — not a missing AST recognizer.

        Dig the callsite floor when the body projects; undiggable residual
        re-dispatches on ``SymbolicValue(self.term)`` so BinaryOperatorOperation
        mints a joinable symbolic op. Never fabricate a concrete fold.
        """
        return self._dig_or_symbolic_redispatch(
            operation, ctx, owner_suffix="callsite binary operand"
        )

    def subscript_with(self, operation, ctx):
        """Subscript on a callsite result (revealed after binary dig progress).

        Same dig-or-symbolic totalizer as binary_operator_with.
        """
        return self._dig_or_symbolic_redispatch(
            operation, ctx, owner_suffix="callsite subscript receiver"
        )

    def _dig_or_symbolic_redispatch(self, operation, ctx, *, owner_suffix: str):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.operations import perform_operation

        # Dig when the body floors; opaque residual re-dispatches on the EUF
        # receiver term (SymbolicValue(self.term)) — honest uninterpreted join,
        # not a catchable gap / dig-boundary third state.
        floor = self._dig_floor_or_none(
            ctx,
            owner=f"{operation.owner} {owner_suffix}",
        )
        receiver: FloorValue = floor if floor is not None else SymbolicValue(self.term)
        return perform_operation(
            owner=operation.owner,
            blame=operation.blame,
            receiver=receiver,
            operation=operation,
            ctx=ctx,
        )

    def call_method_with(self, operation: Any, ctx: Any):
        """Compose a method on a callsite receiver.

        Prefer a dug floor when the body projects (``len(a())`` folds the
        returned array). When the receiver is opaque (no diggable body / body
        Incomplete), compose as an honest EUF join
        ``call:<method>(call:<receiver>(…))`` — same uninterpreted family as
        ``SymbolicValue.call_method_with`` / ``OpaqueOpCallsite``. Never invent
        a numeric value; never soft-catch a panic into Incomplete.
        """
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
        from sugar_lift_py_tests.operations import perform_operation
        from sugar_lift_py_tests.outcome import Complete

        floor = self._dig_floor_or_none(
            ctx,
            owner=f"{operation.owner} callsite method receiver",
        )
        if floor is not None:
            return perform_operation(
                owner=operation.owner,
                blame=operation.blame,
                receiver=floor,
                operation=operation,
                ctx=ctx,
            )
        # Opaque receiver with a real EUF term: join, do not force_floor-panic.
        if operation.name == "__len__" and not operation.arguments:
            return Complete(OpaqueOpCallsite(callee="len", arg=self, computed=None))
        if not operation.name.startswith("__") and all(
            isinstance(arg, FloorValue) for arg in operation.arguments
        ):
            return Complete(
                OpaqueOpCallsite(
                    callee=operation.name,
                    arg=self,
                    computed=None,
                    extra_args=tuple(operation.arguments),
                )
            )
        # Genuinely non-composable (no method coordinate shape) — panic loud.
        _force_floor_gap(
            owner=operation.owner,
            target_name=self.target_name,
            observed=f"non-composable method `{operation.name}` on opaque callsite",
            fix=(
                f"callsite `{self.target_name}.{operation.name}` has no diggable "
                "floor and no EUF method-join shape; cite a warrant or keep red"
            ),
        )

    def _dig_floor_or_none(
        self,
        ctx: Any,
        *,
        owner: str,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
        budget: int = _FORCE_FLOOR_BUDGET,
    ) -> FloorValue | None:
        """Return a concrete floor when dig succeeds; None when the receiver is opaque.

        Opaque (missing body, Incomplete reduce) is an EUF-join residual — not a
        panic and not a soft DigBoundary row. Budget / recursive demand still
        panics: those are non-composable, not joinable coordinates.
        """
        key = repr(self.term)
        if depth >= budget or len(seen) >= budget:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite value demand budget exhausted",
                fix=(
                    f"callsite `{self.target_name}` exceeded force_floor dig budget "
                    f"{budget}; leave the bridge as axiomatic"
                ),
            )
        if key in seen:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="recursive callsite value demand",
                fix=(
                    f"callsite `{self.target_name}` recursively demanded its own "
                    "floor; leave the bridge as axiomatic"
                ),
            )
        if (body := self.body) is None:
            return None
        if len(self.parameters) != len(self.arg_values):
            return None
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(ctx, self.parameters, self.arg_values)
        try:
            outcome = _reduce_callsite_body(body, reduce_ctx, blame=self.target_name)
        except Exception as exc:
            # FactoryPanic mid-dig: opaque residual, not process-terminal for dig_floor.
            from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

            if isinstance(exc, FactoryPanic):
                return None
            raise
        if isinstance(outcome, Incomplete):
            return None
        value = complete_value(outcome, owner=owner)
        if isinstance(value, CallSiteValue):
            return value._dig_floor_or_none(
                reduce_ctx,
                owner=owner,
                seen=seen | {key},
                depth=depth + 1,
                budget=budget,
            )
        return value

    def force_floor(
        self,
        ctx: Any,
        *,
        owner: str,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
        budget: int = _FORCE_FLOOR_BUDGET,
        project_callsite: bool = True,
    ):
        key = repr(self.term)
        if depth >= budget or len(seen) >= budget:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite value demand budget exhausted",
                fix=(
                    f"callsite `{self.target_name}` exceeded force_floor dig budget "
                    f"{budget}; leave the bridge as axiomatic and record a DigBoundary"
                ),
            )
        if key in seen:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="recursive callsite value demand",
                fix=(
                    f"callsite `{self.target_name}` recursively demanded its own "
                    "floor; leave the bridge as axiomatic and record a DigBoundary"
                ),
            )
        if (body := self.body) is None:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="missing callsite body",
                fix=(
                    f"carry a factory-built body for callsite `{self.target_name}` "
                    "or leave the bridge as axiomatic"
                ),
            )
        if len(self.parameters) != len(self.arg_values):
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite arity mismatch",
                fix=(
                    f"callsite `{self.target_name}` argument count does not match "
                    "its body; add argument binding sugar or leave the bridge axiomatic"
                ),
            )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(ctx, self.parameters, self.arg_values)
        outcome = _reduce_callsite_body(body, reduce_ctx, blame=self.target_name)
        if isinstance(outcome, Incomplete):
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="Incomplete",
                fix=(
                    f"callsite `{self.target_name}` reduced to a runtime effect: "
                    f"{outcome.reason}; leave the floor absent and record a DigBoundary"
                ),
            )
        value = complete_value(outcome, owner=owner)
        floor = force_floor(
            value,
            reduce_ctx,
            owner=owner,
            seen=seen | {key},
            depth=depth + 1,
            budget=budget,
            project_callsite=project_callsite,
        )
        if project_callsite:
            _project_callsite_floor(
                floor,
                reduce_ctx,
                owner=owner,
                target_name=self.target_name,
                arg_values=self.arg_values,
            )
        return floor


def force_floor(
    value: FloorValue,
    ctx: Any,
    *,
    owner: str,
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
    budget: int = _FORCE_FLOOR_BUDGET,
    project_callsite: bool = True,
) -> FloorValue:
    if isinstance(value, CallSiteValue):
        return value.force_floor(
            ctx,
            owner=owner,
            seen=seen,
            depth=depth,
            budget=budget,
            project_callsite=project_callsite,
        )
    return value


def _reduce_callsite_body(
    body: SugarBody[Any] | FunctionBodyUniverse,
    ctx: Any,
    *,
    blame: str,
):
    if isinstance(body, SugarBody):
        return body.reduce(ctx)
    if isinstance(body, FunctionBodyUniverse):
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

        return BlockSugar(statements=body.statements, blame=blame).desugar(ctx)
    _force_floor_gap(
        owner="CallSiteValue.force_floor",
        target_name=blame,
        observed=type(body).__name__,
        fix="carry a SugarBody or FunctionBodyUniverse before demanding a callsite floor",
    )


def _project_callsite_floor(
    floor: FloorValue,
    ctx: Any,
    *,
    owner: str,
    target_name: str,
    arg_values: tuple[FloorValue, ...],
) -> None:
    # Currying is already recorded by curry_temporal. Projection contributes
    # proof/callsite state but must not fabricate a second operation event.
    del floor, ctx, owner, target_name, arg_values


def _force_floor_gap(
    *,
    owner: str,
    target_name: str,
    observed: str,
    fix: str,
) -> NoReturn:
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow,
        factory_panic,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=target_name,
        observed=observed,
        requested="force callsite floor",
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.PROJECTION,
    )
    factory_panic(
        info,
        FactoryAuditRow(
            role="force_floor",
            status=FactoryAuditStatus.FLOOR_GAP,
            observed=observed,
            blame=target_name,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _ctx_with_curried_args(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
):
    from sugar_lift_py_tests.temporal import curry_temporal

    return curry_temporal(
        ctx,
        parameters,
        arg_values,
        owner="CallSiteValue.force_floor",
        blame="<callsite>",
    )
