"""Floor projection of a tree-native effect coordinate.

``EffectRef(S)`` always desugars to ``effect-slot(S)`` — a pure coordinate.
Authentication is **not** stored here. The router emits EffectBinding facts
into the same record (effect_slot_kind / type / identity). Missing binding
is an open obligation elsewhere, never a quietly usable observed-exception term.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .floor_value import FloorValue


@dataclass(frozen=True)
class EffectCoordinate(FloorValue):
    """Coordinate only. Always projects ``python:effect_slot(slot_id)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:effect_slot", [str_const(self.slot_id)])

    def is_identical(self, other, site):
        return slot_identity(self, other, site, super().is_identical(other, site))

    def attribute(self, name, site, ctx):
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import effect_slot_source

        if (
            effect_slot_source(self.slot_id).endswith("#enter_result")
            and type(self) is EffectCoordinate
        ):
            # ``with m as r: r.x`` read through the body's enter-result slot:
            # the value ``__enter__`` returned at that one entry, whose runtime
            # type nothing here testified to.  The opaque attribute law holds:
            # complete under ``python:attribute.completes``, otherwise an
            # undetermined raise; no member value or exception is invented.
            return self.undecided_attribute(
                name, site, owner="EffectCoordinate.attribute"
            )
        if name != "__context__":
            return super().attribute(name, site, ctx)
        from sugar_lift_py_tests.gap.info import GapKind
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="EffectCoordinate.attribute.__context__",
            blame=site,
            observed="consumed raise carries no authenticated context preimage",
            requested="the raised value of the in-flight RaiseEffect occurrence",
            fix=(
                "preserve Python exception chaining through the raise effect; "
                "never fabricate an empty chained exception"
            ),
            gap_kind=GapKind.FLOOR,
        )


@dataclass(frozen=True)
class ExceptionInfoCoordinate(FloorValue):
    """Observation wrapper: ``.value`` is the same pure effect coordinate."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exception_info", [str_const(self.slot_id)])

    def is_identical(self, other, site):
        return slot_identity(self, other, site, super().is_identical(other, site))

    def attribute(self, name, site, ctx):
        if name == "value":
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(EffectCoordinate(slot_id=self.slot_id, site=site))
        return super().attribute(name, site, ctx)


@dataclass(frozen=True)
class ObservedEffectValue(EffectCoordinate):
    """Authenticated producer testimony for one consumed RaiseEffect."""

    effect: object = dataclass_field(compare=False, default=None)

    def attribute(self, name, site, ctx):
        if name != "__context__":
            return super().attribute(name, site, ctx)
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import ExitSet

        context = getattr(self.effect, "context_effect", None)
        value = getattr(context, "raised_value", None)
        if isinstance(context, RaiseEffect) and isinstance(value, FloorValue):
            return ExitSet.completed(value)
        return super().attribute(name, site, ctx)


_SLOT_FAMILIES = (EffectCoordinate, ExceptionInfoCoordinate)


def reads_an_effect_slot(value) -> bool:
    """Whether ``value`` is the coordinate of an effect slot: what an
    ``except ... as e``, a ``with ... as x`` or a ``pytest.raises ... as ei``
    binds where nothing deposited a decided value (``EffectRefSugar``,
    ``ObservationRefSugar``)."""
    return isinstance(value, _SLOT_FAMILIES)


def slot_identity(slot, other, site, outcome):
    """``slot is other`` where ``slot`` is an effect slot's coordinate
    (``reads_an_effect_slot``), ``outcome`` the identity the floor emitted.

    A slot's coordinate (``python:effect_slot(<slot>)``,
    ``python:exception_info(<slot>)``) is a value prove does not interpret:
    the facts on it (``EffectBinding``, ``EnterResultBinding``) state its
    kind, type, origin and enter value, never which object it is.  The one
    term is one object: the same slot read twice -- one evaluation of the
    binding (``effect_slot_here``) -- is ``outcome``, decided by the term
    itself.  Any other operand -- the slot of another live loop item, another
    handler, an object made elsewhere -- names an object nothing relates to
    this one.  ``=`` over two such terms is a choice the solver makes, and a
    claim is ``sat`` where some choice satisfies it, so ``errs[0] is
    errs[1]`` over two items' ``e`` could read ``sat`` though Python raised
    two objects.  So that identity is the undecided read: ``outcome`` still
    stands, and every claim that reads it owes the undecided member, by the
    one rule a value nothing decides owes by (``owing_undecided_slot``,
    #7757 step 6)."""
    for family in _SLOT_FAMILIES:
        if isinstance(slot, family) and isinstance(other, family):
            if slot.slot_id == other.slot_id:
                return outcome
            break
    # Even against a language singleton (``e is None``): the slot's term is
    # a coordinate nothing states the value of, so ``term_identity``'s
    # singleton reading has no value to read.  The one rule.
    from sugar_lift_py_tests.floor.object_identity import undecided_identity

    return undecided_identity(outcome, site)


def _language_exception_class_for_coordinate(coordinate):
    """The language-owned class named by a builtins exception-type coordinate.

    Looks up the same BuiltinExceptionClassValue the builtin temporal already
    bound. Does not mint a second copy, and does not invent a class from a
    non-builtin or unnamed coordinate.
    """
    if getattr(coordinate, "name", None) != "python:exception_type_identity":
        return None
    args = getattr(coordinate, "args", ())
    if len(args) != 2:
        return None
    module = getattr(args[0], "value", None)
    name = getattr(args[1], "value", None)
    if module != "builtins" or not isinstance(name, str):
        return None
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_NAMES,
        builtin_name_temporal,
    )

    if name not in BUILTIN_EXCEPTION_NAMES:
        return None
    typ = builtin_name_temporal().value_if_bound(name)
    identity = getattr(typ, "exception_type_identity", None)
    if typ is None or identity is None or identity() != coordinate:
        return None
    return typ


@dataclass(frozen=True)
class ObservedExceptionInfoValue(ExceptionInfoCoordinate):
    """Authenticated assertion-manager observation that outlives its block."""

    effect: object = dataclass_field(compare=False, default=None)

    def attribute(self, name, site, ctx):
        if name == "value":
            from sugar_lift_py_tests.floor.floor_value import FloorValue
            from sugar_lift_py_tests.outcome import ExitSet

            raised = getattr(self.effect, "raised_value", None)
            if isinstance(raised, FloorValue):
                return ExitSet.completed(raised)
            return FloorValue.attribute(self, name, site, ctx)
        if name == "type":
            from sugar_lift_py_tests.outcome import ExitSet

            typ = _language_exception_class_for_coordinate(
                getattr(self.effect, "exception_type_coordinate", None)
            )
            if typ is not None:
                return ExitSet.completed(typ)
        return super().attribute(name, site, ctx)
