from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
import inspect
from typing import Any, Callable, ClassVar, List, cast

from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar.witnesses import SugarWitnesses
from sugar_lift_py_tests.sugar_body import SugarBody


class Sugar(ABC):
    """One sugar is one class, with exactly two behaviors.

      * ``owns(fragment)`` -- static recognition. A sugar owns exactly what it
        lifts; it can never recognize-and-panic. This is the ``Some`` in
        ``match(Sugar) { Some => cite_or_effect, None => panic }``.
      * ``desugar(ctx)`` -- reduce this sugar (already constructed with its body
        sugars) by dispatching operations onto floor values and recursively
        desugaring its bodies. Returns ONE thing: ``Outcome`` = ``Complete`` (a
        floor value) or ``Incomplete`` (a runtime effect that propagates itself).

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

    @classmethod
    @abstractmethod
    def witnesses(cls) -> SugarWitnesses:
        """The truthful/lying twin pair that proves this sugar discriminates."""

    @abstractmethod
    def desugar(self, ctx: object = None) -> Outcome:
        """Reduce this sugar to an Outcome, recursively desugaring its body
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
