from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import fields, is_dataclass
import inspect
from typing import Any, Callable, ClassVar, List, cast

from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar.witnesses import SugarWitnesses
from sugar_lift_py_tests.sugar_body import SugarBody

_STAMPED_REDUCE: list = []

# ``(sugar, ctx)``: the sugar whose evaluation is running now and the context
# it was handed (``Sugar.desugar``), or None outside every evaluation.  What a
# sugar evaluated inside it reads as its evaluator (``_recorded_at_its_head``),
# and what a consumer's step reads as the context its operands were evaluated
# from (``named_expression_value.consume_operands``).
_EVALUATING: ContextVar = ContextVar("sugar_evaluating", default=None)


def evaluating():
    """``(sugar, ctx)``: the sugar whose evaluation is running now and the
    context it was handed, or None outside every evaluation."""
    return _EVALUATING.get()


def _recorded_at_its_head(sugar, ctx, outcome, evaluator):
    """``outcome`` -- ``sugar`` evaluated in ``ctx`` by ``evaluator`` -- with
    every halt that offers no record carrying the record of where ``sugar``
    was evaluated, where ``sugar`` is an expression that holds no walrus and
    ``evaluator`` (the sugar that evaluated it) holds one.

    THE ONE expression evaluation every statement's operands go through, so
    every one of them is held to it: an assignment's right-hand sides, an
    ``if``/``while`` test, a loop's iterable, a ``match`` subject, a ``with``
    item, a ``return``/``raise``/``yield`` operand, an ``assert`` test, every
    operand of every expression.  A walrus binds as its operand completes,
    before a later operand halts (``if (a := f()) and g():``: ``a`` is bound
    when ``g()`` raises); the halt's record is built from the binds already
    made, which the context the later operand was evaluated in holds
    (``written_by``), and never stood in for by the statement's head, which
    holds none of them (``function_universe_sugar.halts_at_operand_head``).
    An expression that holds a walrus records nothing here: its own
    walrus-free operands recorded theirs, and its step's halt is recorded
    with its operands' binds (``consume_operands``).  Where the evaluator
    holds no walrus nothing is bound by it before the halt, and the halt is
    handed on as it is (a statement records it at its head).  A statement
    reduced as a statement records its own halts (``_require_recorded_halts``)."""
    if (
        evaluator is None
        or not isinstance(sugar, ConstructedTermSugar)
        or not isinstance(outcome, ExitSet)
        or not any(
            isinstance(exit_, Halted) and exit_.state is None
            for exit_ in outcome.exits
        )
    ):
        # The common case, read before anything is imported: no halt here
        # offers no record.
        return outcome
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        halts_at_operand_head,
    )
    from sugar_lift_py_tests.sugar.named_expr_sugar import holds_a_walrus

    if not holds_a_walrus(evaluator[0]):
        return outcome
    return halts_at_operand_head(outcome, sugar, ctx)


def _reduce_at_stamped_module_execution_site():
    """``sugar_source_tree.nodes.reduce_at_stamped_module_execution_site``,
    imported once (the tree package imports this one lazily)."""
    if not _STAMPED_REDUCE:
        from sugar_source_tree.nodes import reduce_at_stamped_module_execution_site

        _STAMPED_REDUCE.append(reduce_at_stamped_module_execution_site)
    return _STAMPED_REDUCE[0]


class Sugar(ABC):
    """One sugar is one class, with exactly two behaviors.

      * ``owns(fragment)`` -- static recognition. A sugar owns exactly what it
        lifts; it can never recognize-and-panic. This is the ``Some`` in
        ``match(Sugar) { Some => cite_or_effect, None => panic }``.
      * ``desugar(ctx)`` -- reduce this sugar (already constructed with its body
        sugars) by dispatching operations onto floor values and recursively
        desugaring its bodies. Returns ONE thing: an ``ExitSet`` whose
        ``Completed`` arms hold floor values and whose ``Halted`` arms hold the
        runtime effects that propagate themselves.

    There is no ``build`` and no ``_build``. Construction is just ``new``: the
    factory recognizes, then constructs the sugar WITH its body sugars, then calls
    ``desugar``. A sugar never asks "which arm are you" of any value -- floor
    values and outcomes answer by being called (double dispatch). The only thing
    that stops a lift is nothing recognizing the source: that is the ``None`` arm,
    and it is a panic, never a soft third state.

    A concrete sugar defines ``desugar`` and ``witnesses`` (enforced by ABC).
    It is constructed WITH its body sugars by the AST node's ``.sugar()``; it
    never recognizes and never registers — recognition is the node's job.
    """

    effect_consumer_reason: ClassVar[str | None] = None
    universe_coordinates: ClassVar[frozenset[str]] = frozenset()
    # A simple statement whose only work is evaluating its expression(s) and
    # then completing, returning or raising. It binds nothing before its own
    # halt, so a halted arm it hands back without a temporal record halted at
    # the head of the statement: the enclosing block's prefix IS that arm's
    # pre-halt state. Compound statements (if/for/while/with/try/match) never
    # set this: some of their halts happen after a body ran, and the prefix
    # would erase that body's record. Every halt they hand back carries its
    # own record instead (``function_universe_sugar.halt_record``: the empty
    # one where it halted, for a halt at the statement's head). A statement
    # that does not set this and hands the block reducer a halt with no
    # record is refused by name (``_require_recorded_halts``). The claim is
    # checked there, not trusted: it holds only for a statement that holds
    # no walrus (``named_expr_sugar.holds_a_walrus``) -- a walrus binds as
    # its operand completes, before a later operand halts, and that halt's
    # record is built from the binds already made (``halts_at_operand_head``).
    halts_at_statement_head: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get("desugar")
        if own is None or getattr(own, "_answers_assigned_value", False):
            return
        if getattr(own, "__isabstractmethod__", False):
            return
        import functools

        @functools.wraps(own)
        def desugar(self, ctx=None, *args, **kwargs):
            tags = self.__dict__.get("_occurrence_tags") if hasattr(
                self, "__dict__"
            ) else None
            if tags:
                # This sugar is one iteration's copy of its node: every site
                # under it is evaluated in that iteration (occurrence.py).
                from sugar_lift_py_tests.occurrence import (
                    current_path,
                    occurrence_path,
                )

                path = current_path()
                if path[len(path) - len(tags):] != tags:
                    with occurrence_path((*path, *tags)):
                        return desugar(self, ctx, *args, **kwargs)
            # A RHS an assignment statement already evaluated answers with
            # the value of the face it completed under; a read never
            # re-evaluates it (sugar/assigned_value.py).
            if ctx is not None and getattr(ctx, "assigned_values", None):
                from sugar_lift_py_tests.sugar.assigned_value import (
                    _MISS,
                    recorded_value,
                )

                value = recorded_value(ctx, self)
                if value is not _MISS:
                    return ExitSet.completed(value)
            # A sugar stamped with where the module body runs its node
            # reduces there: an implicit call it makes (``__add__``,
            # ``__getitem__``, a property getter) reads a module global as
            # the module binds it at that point (#7757 item 7).
            evaluator = _EVALUATING.get()
            token = _EVALUATING.set((self, ctx))
            try:
                outcome = _reduce_at_stamped_module_execution_site()(
                    self, lambda: own(self, ctx, *args, **kwargs)
                )
            finally:
                _EVALUATING.reset(token)
            # A halt of an operand carries the walrus binds made before it
            # (``_recorded_at_its_head``).
            return _recorded_at_its_head(self, ctx, outcome, evaluator)

        desugar._answers_assigned_value = True
        cls.desugar = desugar

    @classmethod
    @abstractmethod
    def witnesses(cls) -> SugarWitnesses:
        """The truthful/lying twin pair that proves this sugar discriminates."""

    @abstractmethod
    def desugar(self, ctx: object = None) -> ExitSet:
        """Reduce this sugar to an ExitSet, recursively desugaring its body
        sugars. The one semantic verb; a sugar constructed with sugar."""

    def walk_children(self) -> tuple[SugarBody, ...]:
        # Default: a leaf. Sugars that hold SugarBody children override to
        # return them in source order -- the factory walk projects those.
        return ()


class ConstructedTermSugar(Sugar):
    """Sugar admitted as canonical generator/nested-construction testimony."""

    @abstractmethod
    def to_term(self, *, owner: str) -> Term:
        """Project authenticated construction testimony into canonical IR."""

    def occurrence_term(self, *, owner: str) -> Term:
        """Seal the exact source occurrence; identical spelling elsewhere differs."""
        from sugar_lift_py_tests.ir import ctor, num, str_const

        try:
            occurrence = self.site.seal()
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                f"{owner} requires an authenticated source occurrence for "
                f"{type(self).__name__}"
            ) from exc
        return ctor(
            "python:source-occurrence",
            (
                str_const(occurrence.source_cid),
                num(occurrence.start),
                num(occurrence.end),
                str_const(occurrence.cid),
            ),
            symbol_kind="coordinate",
        )


def require_constructed_term_sugar(
    value: object, *, owner: str
) -> ConstructedTermSugar:
    """Close a nested construction payload before canonical projection.

    ONE codomain law for every nested term slot (CallSiteSugar.args /
    keywords, MethodCallSugar.args / keywords, IfExp arms, BinOpSugar
    left/right, UnaryOpSugar.operand, EqualityOpSugar, Subscript index, …).
    Admission is hierarchy: ConstructedTermSugar + to_term — including:

    - L2a: SpreadCollectionSugar, SpreadDictSugar, SpreadCallSugar, StarredSugar
    - L2b: ComplexLiteralSugar, EllipsisLiteralSugar, and sibling leaves
      (Int/Real/String/Bytes/None/True/False)

    Do not special-case species at individual call sites; promote the mint,
    keep this door.
    """
    if not isinstance(value, ConstructedTermSugar):
        raise TypeError(
            f"{owner} requires ConstructedTermSugar, got {type(value).__name__}"
        )
    return value
