from __future__ import annotations

from abc import ABC
from typing import List

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.sugar.witnesses import SugarWitnesses

# Every Sugar subclass that declares a role self-registers its claim here at import
# time, so the catalog is just this list -- no hand-wired CLAIM constants, impossible
# to forget to register a new sugar.
_REGISTRY: List[SugarClaim] = []
_REGISTRATION_SITES: dict[str, str] = {}


def registered_claims() -> List[SugarClaim]:
    return list(_REGISTRY)


def validate_registry() -> None:
    """Refuse invalid registry topology before factory dispatch can see it."""

    _refuse_duplicate_claims()
    _refuse_dangling_comes_before()
    _refuse_comes_before_cycles()


def _claimant(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _refuse_duplicate_claim(cls: type) -> None:
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


def _refuse_duplicate_claims() -> None:
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


def _refuse_dangling_comes_before() -> None:
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


def _refuse_comes_before_cycles() -> None:
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
    """One sugar is one class.

    A leaf subclass declares its dispatch role and provides three things:
      * ``owns(fragment)``  -- the recognizer over a SourceFragment (was a loose
        module-level ``_owns``),
      * ``build(fragment, ctx)`` -- the constructor that composes child fragments
        through the factory (``ctx.build_body``) and hands them to ``__init__`` (was a
        loose ``build_X`` in sugar_constructors),
      * ``desugar(ctx)`` -- the reduction to a Floor value.

    Declaring ``class XSugar(Sugar, role=SugarRole.TERM)`` SELF-REGISTERS the claim
    into the catalog. A base with no ``role=`` is an intermediate (not registrable).

    Construction law: only ``build`` may call ``ctx.build_body`` (it constructs the
    children). ``desugar`` must never pull its own body -- the factory already handed
    the composed children to ``__init__``.
    """

    role: SugarRole

    def __init_subclass__(
        cls,
        role: SugarRole | None = None,
        comes_before: tuple = (),
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if role is None:
            return  # an intermediate base (e.g. a shared mixin), not a registrable leaf
        if "witnesses" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} is a registrable sugar but does not define "
                "witnesses(); enrollment is existence"
            )
        _refuse_duplicate_claim(cls)
        cls.role = role
        claim = SugarClaim(
            name=cls.__name__,
            role=role,
            owns=cls.owns,
            build=cls.build,
            comes_before=tuple(comes_before),
            witnesses=cls.witnesses,
        )
        _REGISTRY.append(claim)
        _REGISTRATION_SITES[claim.name] = _claimant(cls)
        _refuse_comes_before_cycles()

    @classmethod
    def owns(cls, fragment) -> bool:
        raise NotImplementedError(f"{cls.__name__} must define owns(fragment)")

    @classmethod
    def build(cls, fragment, ctx) -> "Sugar":
        raise NotImplementedError(f"{cls.__name__} must define build(fragment, ctx)")

    @classmethod
    def witnesses(cls) -> SugarWitnesses:
        raise NotImplementedError(f"{cls.__name__} must define witnesses()")

    def desugar(self, ctx):
        raise NotImplementedError(f"{type(self).__name__} must define desugar(ctx)")
