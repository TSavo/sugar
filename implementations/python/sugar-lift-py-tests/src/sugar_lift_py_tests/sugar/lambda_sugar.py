"""A narrow expression-bodied lambda callable."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class LambdaSugar(ConstructedTermSugar):
    """Plain positional formals plus one already-constructed body expression.

    ``closure_coordinates`` are the final-member coordinates the body reads
    through an enclosing comprehension's cell (#7757 item 7,
    ``Lambda._closure_coordinates``).  The comprehension binds them before it
    reduces the element; the lambda value carries each binding (its closure,
    ``LambdaCallable.closure``), so its body reduces after the comprehension
    is done, when the context no longer binds them.

    ``evaluation_coordinates`` are ``(lambda's coordinate, comprehension's
    coordinate)`` for each comprehension cell the body reads at the call
    (every lambda made in a comprehension, ``Lambda._evaluation_coordinates``):
    the
    value carries, under the lambda's coordinate, the evaluation of the
    comprehension it was made in, so a call compares it with the evaluation
    running at the call (``EvaluationRefSugar``).  A generator expression
    not consumed whole in place binds no final member
    (``ComprehensionSugar.final_member``): its lambda carries none, and a
    call outside a run of the generator is refused by name.

    An enclosing function's local the body reads is read through a captured
    coordinate (``Lambda._captured_bindings``) that each call binds from the
    calling scope at the call (``ComputedCallSugar.captured``), never the
    binding at construction.  ``captured`` is that binding at a call this
    lambda is passed to, whose callee runs it during the call
    (``Call._carry_argument_cells``): ``((name, coordinate cid, sugar),
    ...)``, read where the argument is evaluated and carried on the value
    (``LambdaCallable.captured``).

    ``defaults`` are ``((key, sugar), ...)``, one per formal with a default,
    in source order: Python evaluates a lambda's defaults where the lambda
    expression is evaluated, left to right, and every call that omits the
    formal binds that one object.  ``desugar`` evaluates each here, under the
    state the ones before it leave; a default that halts is a face of the
    lambda expression, and a completed one is carried on the value under its
    key (``LambdaCallable.defaults``), which every call binds
    (``object_value.bind_call``) and the frame reads (``DefaultValueSugar``)."""

    formals: tuple[str, ...]
    body: Sugar
    source_call_frame: object
    formal_coordinate_cids: tuple[str, ...]
    body_fragment_cid: str
    site: object = dataclass_field(compare=False)
    closure_coordinates: tuple[str, ...] = ()
    captured: tuple = dataclass_field(default=(), compare=False)
    evaluation_coordinates: tuple[tuple[str, str], ...] = ()
    defaults: tuple[tuple[str, Sugar], ...] = dataclass_field(
        default=(), compare=False
    )

    def __post_init__(self) -> None:
        from sugar_source_tree.panic import SugarNotWritten

        frame = self.source_call_frame
        if tuple(frame.parameters) != self.formals:
            raise SugarNotWritten(
                owner="LambdaSugar.formals",
                blame=self.site,
                observed=(
                    f"frame.parameters={tuple(frame.parameters)!r} "
                    f"!= formals={self.formals!r}"
                ),
                requested="formals identical to the authenticated source_call_frame",
                fix=(
                    "construct LambdaSugar only from Lambda._construct_sugar with "
                    "the producer frame; do not invent formals"
                ),
            )
        if tuple(coordinate.cid for coordinate in frame.formal_coordinates) != (
            self.formal_coordinate_cids
        ):
            raise SugarNotWritten(
                owner="LambdaSugar.formal_coordinate_cids",
                blame=self.site,
                observed="formal_coordinate_cids disagree with frame.formal_coordinates",
                requested="producer-authenticated formal coordinate CID tuple",
                fix="carry coordinate CIDs from the source_visible_call_frame only",
            )
        if frame.definition_fragment_cid != self.site.seal().cid:
            raise SugarNotWritten(
                owner="LambdaSugar.source_call_frame",
                blame=self.site,
                observed=(
                    f"frame.definition_fragment_cid={frame.definition_fragment_cid!r} "
                    f"!= lambda site cid={self.site.seal().cid!r}"
                ),
                requested="source frame pinned to this exact lambda occurrence",
                fix="mint the frame at the Lambda node; do not reuse another definition",
            )
        if self.body.site.seal().cid != self.body_fragment_cid:
            raise SugarNotWritten(
                owner="LambdaSugar.body",
                blame=getattr(self.body, "site", self.site),
                observed=(
                    f"body site cid={self.body.site.seal().cid!r} "
                    f"!= body_fragment_cid={self.body_fragment_cid!r} "
                    f"(body type={type(self.body).__name__})"
                ),
                requested=(
                    "body sugar whose site.seal().cid equals the exact source "
                    "body fragment CID captured at construction"
                ),
                fix=(
                    "construct the body from the Lambda expression body node "
                    "before rewrite; a substituted/rewritten body with a different "
                    "fragment is an honest gap until rewrite preserves body "
                    "occurrence identity — refuse specifically, never TypeError"
                ),
            )

    @classmethod
    def witnesses(cls):
        prefix = "def A(v):\n    return (lambda x: x)(v)\n\n"
        return _call_pair(
            name="lambda_identity_call",
            owner_sugar="LambdaSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor import LambdaCallable
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )
        from sugar_lift_py_tests.sugar.call_site_sugar import carried_captured_values

        sealed = self.site.seal()
        construction_identity = (
            f"{sealed.source_cid}@{sealed.start}:{sealed.end}#{sealed.cid}"
        )
        keys = tuple(key for key, _sugar in self.defaults)

        def construct(*values) -> ExitSet:
            return ExitSet.completed(
                LambdaCallable(
                    parameters=self.formals,
                    body=self.body,
                    construction_identity=construction_identity,
                    source_call_frame=self.source_call_frame,
                    defaults=tuple(zip(keys, values, strict=True)),
                    closure=self._closure(ctx),
                    captured=carried_captured_values(self.captured, ctx),
                )
            )

        if not self.defaults:
            return construct()
        # The defaults are the lambda expression's operands: evaluated left
        # to right, each halt a face of the expression, and a walrus in one
        # binds once, through the one operand door.
        return reduce_operands(
            tuple(sugar for _key, sugar in self.defaults), ctx
        ).and_then(lambda values: consume_operands(construct, *values))

    def _closure(self, ctx) -> tuple:
        """Each closure coordinate ``ctx`` binds, with the value bound: what
        the enclosing comprehension's cell holds once it is done.  Then,
        under each lambda's evaluation coordinate, the evaluation of the
        comprehension running where the lambda is made.  A coordinate ``ctx``
        does not bind is not carried; a later reduction of the body reads it
        unbound and refuses, as before."""
        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            return ()
        closure = []
        for coordinate in self.closure_coordinates:
            value = temporal.value_if_bound(coordinate)
            if value is not None:
                closure.append((coordinate, value))
        for carried, running in self.evaluation_coordinates:
            value = temporal.value_if_bound(running)
            if value is not None:
                closure.append((carried, value))
        return tuple(closure)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, num, str_const

        body_occurrence = self.body.site.seal()

        return ctor(
            "python:lambda-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:lambda-formals",
                    tuple(
                        ctor(
                            "python:lambda-formal",
                            (str_const(name), str_const(coordinate_cid)),
                            symbol_kind="coordinate",
                        )
                        for name, coordinate_cid in zip(
                            self.formals, self.formal_coordinate_cids, strict=True
                        )
                    ),
                ),
                ctor(
                    "python:lambda-body",
                    (
                        str_const(body_occurrence.source_cid),
                        num(body_occurrence.start),
                        num(body_occurrence.end),
                        str_const(self.body_fragment_cid),
                    ),
                    symbol_kind="coordinate",
                ),
                str_const(self.source_call_frame.frame_cid),
            ),
            symbol_kind="coordinate",
        )
