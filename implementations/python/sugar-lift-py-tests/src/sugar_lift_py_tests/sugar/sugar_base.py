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
    """One sugar is one class.

    A leaf subclass declares its dispatch role and provides three things:
      * ``owns(fragment)``  -- the recognizer over a SourceFragment (was a loose
        module-level ``_owns``),
      * ``build(fragment, ctx)`` -- the constructor that composes child fragments
        through the factory (``ctx.build_body``) and hands them to ``__init__`` (was a
        loose ``build_X`` in sugar_constructors),
      * ``_build(ctx, ...)`` -- the post-child-reduction construction hook.

    Declaring ``class XSugar(Sugar, role=SugarRole.TERM)`` SELF-REGISTERS the claim
    into the catalog. A base with no ``role=`` is an intermediate (not registrable).

    Construction law: only ``build`` may call ``ctx.build_body`` (it constructs the
    children). Subclasses do not override ``desugar``; the template method reduces
    declared operands and propagates effects before calling ``_build``.
    """

    role: SugarRole
    effect_consumer_reason: ClassVar[str | None] = None
    template_operand_names: ClassVar[tuple[str, ...] | None] = None

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
        _reject_duplicate_claim(cls)
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
        _reject_comes_before_cycles()

    @classmethod
    def owns(cls, fragment) -> bool:
        raise NotImplementedError(f"{cls.__name__} must define owns(fragment)")

    @classmethod
    def build(cls, fragment, ctx) -> "Sugar":
        raise NotImplementedError(f"{cls.__name__} must define build(fragment, ctx)")

    @classmethod
    def witnesses(cls) -> SugarWitnesses:
        raise NotImplementedError(f"{cls.__name__} must define witnesses()")

    def desugar(self, ctx=None) -> Outcome:
        """Reduce declared operands once, then hand complete values to `_build`.

        Ordinary sugars are monadic: their child `SugarBody` operands either reduce
        to complete floor values, or the first `Incomplete` is returned unchanged.
        Sugars that genuinely consume effects use `_desugar_with_effects`, named and
        audited by tests, instead of shadowing this public entrypoint.
        """

        hook = getattr(self, "_desugar_with_effects", None)
        if hook is not None:
            if self.effect_consumer_reason is None:
                raise TypeError(
                    f"{type(self).__name__} defines _desugar_with_effects without "
                    "effect_consumer_reason"
                )
            return cast(Callable[[Any], Outcome], hook)(ctx)

        operands = _complete_declared_operands(self, ctx)
        if isinstance(operands, Incomplete):
            return operands
        return _call_build(self, ctx, operands)

    @abstractmethod
    def _build(self, ctx, **complete_operands) -> Outcome:
        raise NotImplementedError(f"{type(self).__name__} must define _build(ctx)")


def _complete_declared_operands(sugar: Sugar, ctx) -> dict[str, Any] | Incomplete:
    if not is_dataclass(sugar):
        return {}
    complete_operands: dict[str, Any] = {}
    for field in fields(sugar):
        if not _is_template_operand(type(sugar), field.name):
            continue
        value = getattr(sugar, field.name)
        if not _contains_sugar_body(value):
            continue
        complete = _complete_operand(
            value,
            ctx,
            owner=f"{type(sugar).__name__} {field.name}",
        )
        if isinstance(complete, Incomplete):
            return complete
        complete_operands[field.name] = complete
    return complete_operands


def _is_template_operand(cls: type[Sugar], name: str) -> bool:
    declared = cls.template_operand_names
    if declared is not None:
        return name in declared
    return False


def _call_build(sugar: Sugar, ctx, operands: dict[str, Any]) -> Outcome:
    build_hook = cast(Callable[..., Outcome], sugar._build)
    signature = inspect.signature(build_hook)
    params = signature.parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return build_hook(ctx, **operands)
    build_params = [
        param
        for param in params.values()
        if param.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    ]
    if not build_params:
        return build_hook()
    if len(build_params) == 1 and build_params[0].name == "ctx":
        return build_hook(ctx)
    operand_names = {param.name for param in build_params if param.name != "ctx"}
    if operand_names and operand_names.issubset(operands):
        kwargs = {name: operands[name] for name in operand_names}
        if "ctx" in {param.name for param in build_params}:
            return build_hook(ctx, **kwargs)
        return build_hook(**kwargs)
    return build_hook(ctx)


def _contains_sugar_body(value: Any) -> bool:
    if isinstance(value, SugarBody):
        return True
    if isinstance(value, tuple):
        return any(_contains_sugar_body(item) for item in value)
    return False


def _complete_operand(value: Any, ctx, *, owner: str) -> Any | Incomplete:
    if isinstance(value, SugarBody):
        outcome = value.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        if isinstance(outcome, Complete):
            return outcome.value
        return outcome
    if isinstance(value, tuple):
        completed = []
        for index, item in enumerate(value):
            item_value = _complete_operand(item, ctx, owner=f"{owner}[{index}]")
            if isinstance(item_value, Incomplete):
                return item_value
            completed.append(item_value)
        return tuple(completed)
    return value
