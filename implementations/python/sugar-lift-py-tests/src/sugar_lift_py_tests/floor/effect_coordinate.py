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

    def attribute(self, name, site):
        if self.slot_id.endswith("#enter_result") and type(self) is EffectCoordinate:
            # ``with m as r: r.x`` read through the body's enter-result slot:
            # the value ``__enter__`` returned at that one entry, whose runtime
            # type nothing here testified to.  The opaque attribute law holds:
            # complete under ``python:attribute.completes``, otherwise an
            # undetermined raise; no member value or exception is invented.
            from sugar_lift_py_tests.floor.call_site_value import (
                _opaque_attribute_faces,
            )

            return _opaque_attribute_faces(self, name, site)
        if name != "__context__":
            return super().attribute(name, site)
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

    def attribute(self, name, site):
        if name == "value":
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(EffectCoordinate(slot_id=self.slot_id, site=site))
        return super().attribute(name, site)


@dataclass(frozen=True)
class ObservedEffectValue(EffectCoordinate):
    """Authenticated producer testimony for one consumed RaiseEffect."""

    effect: object = dataclass_field(compare=False, default=None)

    def attribute(self, name, site):
        if name != "__context__":
            return super().attribute(name, site)
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import ExitSet

        context = getattr(self.effect, "context_effect", None)
        value = getattr(context, "raised_value", None)
        if isinstance(context, RaiseEffect) and isinstance(value, FloorValue):
            return ExitSet.completed(value)
        return super().attribute(name, site)


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

    def attribute(self, name, site):
        if name == "value":
            from sugar_lift_py_tests.floor.floor_value import FloorValue
            from sugar_lift_py_tests.outcome import ExitSet

            raised = getattr(self.effect, "raised_value", None)
            if isinstance(raised, FloorValue):
                return ExitSet.completed(raised)
            return FloorValue.attribute(self, name, site)
        if name == "type":
            from sugar_lift_py_tests.outcome import ExitSet

            typ = _language_exception_class_for_coordinate(
                getattr(self.effect, "exception_type_coordinate", None)
            )
            if typ is not None:
                return ExitSet.completed(typ)
        return super().attribute(name, site)
