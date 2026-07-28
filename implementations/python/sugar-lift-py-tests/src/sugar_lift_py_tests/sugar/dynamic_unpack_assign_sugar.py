from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class DynamicUnpackAssignSugar(Sugar):
    """``<name>, <name>, ... = <rhs>`` (optionally with one ``*star``) where
    the RHS is NOT a display.

    The tree cannot pair targets with members here (``Assign._destructured_binding``
    zips displays only), so ``substitution_binding`` threads nothing and the
    names are still unbound when this statement reduces. That is exactly what
    the desugar owes: evaluate the RHS ONCE, then ask the reduced value what it
    unpacks to.

    The answer is the value's, not this sugar's -- ``SequenceProjectionOperation``
    is submitted through the floor's ``project_sequence_with`` port, and the
    value decides:

    - authenticated finite members (tuple/array/list): the arity is lift-time
      decidable, so each name binds to the member ALREADY IN HAND (star binds a
      ``ListValue`` of the middle in source order) and rides forward as a
      ``ScopeRebinds`` support entry -- the same scope threading a mutation
      uses, no second door;
    - runtime cardinality (symbolic / object / opaque coordinate): the count
      belongs to ``__iter__`` at runtime, so the arity demand is retained as a
      typed ``SequenceUnpackRuntimeEffect``. Nothing binds on that arm, exactly
      as CPython binds nothing when ``UNPACK_SEQUENCE`` / ``UNPACK_EX`` raises.
      Starred opaque patterns keep this law: never complete, never invent a tail;
    - anything else: a loud floor construction gap.

    No arm assumes the count matched, and no arm invents a member. The RHS's own
    arms are conserved because it is reduced through ``and_then`` first.
    """

    target_names: tuple[str, ...]
    value: Sugar
    site: object = dataclass_field(compare=False)
    star_name: str | None = None
    prefix_names: tuple[str, ...] = ()
    suffix_names: tuple[str, ...] = ()

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="sequence_unpack_runtime_effect",
            owner_sugar="DynamicUnpackAssignSugar",
            source="def A(o, v):\n    a, b = o\n    return v\n",
            effect_class="SequenceUnpackRuntimeEffect",
            reason_needle="sequence unpack",
            blame_needle="arity=2",
            wrong_reason_needle="unpack demands exactly 3 members",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.operations import SequenceProjectionOperation

        if self.star_name is None:
            operation = SequenceProjectionOperation(
                target_names=self.target_names,
                owner=type(self).__name__,
                blame=self.site,
            )
        else:
            operation = SequenceProjectionOperation(
                target_names=(*self.prefix_names, *self.suffix_names),
                owner=type(self).__name__,
                blame=self.site,
                star_name=self.star_name,
                prefix_names=self.prefix_names,
                suffix_names=self.suffix_names,
            )
        # Python evaluates the right-hand side before it unpacks anything.
        return self.value.desugar(ctx).and_then(
            lambda value: operation.submit(value, ctx)
        )
