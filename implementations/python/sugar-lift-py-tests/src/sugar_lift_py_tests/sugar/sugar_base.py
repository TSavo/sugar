from __future__ import annotations

from abc import ABC
from typing import List

from sugar_lift_py_tests.claim import SugarClaim, SugarRole

# Every Sugar subclass that declares a role self-registers its claim here at import
# time, so the catalog is just this list -- no hand-wired CLAIM constants, impossible
# to forget to register a new sugar.
_REGISTRY: List[SugarClaim] = []


def registered_claims() -> List[SugarClaim]:
    return list(_REGISTRY)


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
        cls.role = role
        _REGISTRY.append(
            SugarClaim(
                name=cls.__name__,
                role=role,
                owns=cls.owns,
                build=cls.build,
                comes_before=comes_before,
            )
        )

    @classmethod
    def owns(cls, fragment) -> bool:
        raise NotImplementedError(f"{cls.__name__} must define owns(fragment)")

    @classmethod
    def build(cls, fragment, ctx) -> "Sugar":
        raise NotImplementedError(f"{cls.__name__} must define build(fragment, ctx)")

    def desugar(self, ctx):
        raise NotImplementedError(f"{type(self).__name__} must define desugar(ctx)")
