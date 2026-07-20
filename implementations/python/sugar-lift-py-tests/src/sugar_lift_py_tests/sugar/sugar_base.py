from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
import inspect
from typing import Any, Callable, ClassVar, List, cast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
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

    Declaring ``class XSugar(Sugar, role=SugarRole.TERM)`` SELF-REGISTERS the claim
    into the catalog. A base with no ``role=`` is an intermediate (not registrable).
    """

    role: SugarRole
    effect_consumer_reason: ClassVar[str | None] = None
    universe_coordinates: ClassVar[frozenset[str]] = frozenset()

    def __init_subclass__(
        cls,
        role: SugarRole | None = None,
        comes_before: tuple = (),  # DEAD: catalog scan-order, no scan exists; ignored,
                                   # removed per-sugar as recognition leaves each file
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if role is None:
            return  # an intermediate base (e.g. a shared mixin), not a leaf sugar
        # A sugar is MEANING: it desugars and it proves itself. Recognition and
        # construction moved onto the AST node (node.sugar()), so a sugar no
        # longer defines owns/new and no longer registers into a factory catalog.
        for required in ("desugar", "witnesses"):
            if required not in cls.__dict__:
                raise TypeError(
                    f"{cls.__name__} is a sugar but does not define {required}(); "
                    "a sugar reduces itself (desugar) and proves itself (witnesses)."
                )
        cls.role = role

    @classmethod
    def witnesses(cls) -> SugarWitnesses:
        raise NotImplementedError(f"{cls.__name__} must define witnesses()")

    def desugar(self, ctx: object = None) -> Outcome:
        raise NotImplementedError(
            f"{type(self).__name__} must define desugar(ctx); a registered sugar "
            "reduces itself to an Outcome (Complete floor value or Incomplete effect)"
        )

    def walk_children(self) -> tuple[SugarBody, ...]:
        # Default: a leaf. Sugars that hold SugarBody children override to
        # return them in source order -- the factory walk projects those.
        return ()
