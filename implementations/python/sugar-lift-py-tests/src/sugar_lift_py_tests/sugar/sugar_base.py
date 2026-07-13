from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
import inspect
from typing import Any, Callable, ClassVar, List, cast

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.witnesses import SugarWitnesses
from sugar_lift_py_tests.sugar_body import SugarBody

# Every Sugar subclass that declares a role self-registers its claim here at import
# time, so the catalog is just this list -- no hand-wired CLAIM constants, impossible
# to forget to register a new sugar.
_REGISTRY: List[SugarClaim] = []
_REGISTRATION_SITES: dict[str, str] = {}


def registered_claims() -> List[SugarClaim]:
    return list(_REGISTRY)


def validate_registry() -> None:
    """Reject invalid registry topology before factory dispatch can see it."""

    _reject_duplicate_claims()
    _reject_dangling_comes_before()
    _reject_comes_before_cycles()


def _claimant(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _reject_duplicate_claim(cls: type) -> None:
    existing = _REGISTRATION_SITES.get(cls.__name__)
    if existing is None:
        return
    claimant = _claimant(cls)
    raise RuntimeError(
        f"duplicate Sugar claim name `{cls.__name__}`: "
        f"first claimant `{existing}`, second claimant `{claimant}`. "
        "Fix: rename one Sugar class or merge the implementations behind one "
        "registered claim name."
    )


def _reject_duplicate_claims() -> None:
    seen: dict[str, str] = {}
    for claim in _REGISTRY:
        site = _REGISTRATION_SITES.get(claim.name, claim.name)
        existing = seen.get(claim.name)
        if existing is not None:
            raise RuntimeError(
                f"duplicate Sugar claim name `{claim.name}`: "
                f"first claimant `{existing}`, second claimant `{site}`. "
                "Fix: rename one Sugar class or merge the implementations behind one "
                "registered claim name."
            )
        seen[claim.name] = site


def _reject_dangling_comes_before() -> None:
    names = {claim.name for claim in _REGISTRY}
    for claim in _REGISTRY:
        for target in claim.comes_before:
            if target not in names:
                raise RuntimeError(
                    "dangling Sugar comes_before reference: "
                    f"`{claim.name}` declares target `{target}`, but no registered "
                    "claim has that name. Fix: rename the comes_before target to an "
                    f"existing Sugar claim or import/register `{target}` before the "
                    "catalog is built."
                )


def _reject_comes_before_cycles() -> None:
    names = {claim.name for claim in _REGISTRY}
    graph = {
        claim.name: tuple(target for target in claim.comes_before if target in names)
        for claim in _REGISTRY
    }
    visited: set[str] = set()
    visiting: list[str] = []

    def visit(name: str) -> list[str] | None:
        if name in visiting:
            return visiting[visiting.index(name) :] + [name]
        if name in visited:
            return None
        visiting.append(name)
        for target in graph.get(name, ()):
            cycle = visit(target)
            if cycle is not None:
                return cycle
        visiting.pop()
        visited.add(name)
        return None

    for claim in _REGISTRY:
        cycle = visit(claim.name)
        if cycle is not None:
            path = " -> ".join(cycle)
            raise RuntimeError(
                f"Sugar comes_before cycle: {path}. Fix: remove one comes_before "
                "edge or split the sugar role so registry precedence is acyclic."
            )


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

    def __init_subclass__(
        cls,
        role: SugarRole | None = None,
        comes_before: tuple = (),
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if role is None:
            return  # an intermediate base (e.g. a shared mixin), not a registrable leaf
        for required in ("owns", "new", "desugar", "witnesses"):
            if required not in cls.__dict__:
                raise TypeError(
                    f"{cls.__name__} is a registrable sugar but does not define "
                    f"{required}(); a sugar owns exactly what it can lift, so to enroll "
                    "it must recognize (owns), construct (new), reduce (desugar), and "
                    "prove itself (witnesses). A sugar that cannot lift cannot own -- "
                    "enrollment is existence, and a half-sugar is a recognize-and-panic "
                    "side door."
                )
        _reject_duplicate_claim(cls)
        cls.role = role
        claim = SugarClaim(
            name=cls.__name__,
            role=role,
            owns=cls.owns,
            comes_before=tuple(comes_before),
            witnesses=cls.witnesses,
            new=cls.new,
        )
        _REGISTRY.append(claim)
        _REGISTRATION_SITES[claim.name] = _claimant(cls)
        _reject_comes_before_cycles()

    @classmethod
    def owns(cls, fragment) -> bool:
        raise NotImplementedError(f"{cls.__name__} must define owns(fragment)")

    @classmethod
    def new(cls, site, ctx) -> "Sugar":
        raise NotImplementedError(
            f"{cls.__name__} must define new(site, ctx); construction builds its "
            "child bodies through the factory (ctx.build_body) and news the sugar"
        )

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
