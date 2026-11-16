from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AttributeDeleteEffectSugar(Sugar):
    """`del receiver.attr` — evaluate once, then project the delete face.

    The delete itself is the one attribute mutation
    (``store_effect_sugar.attribute_mutation``), the same door
    ``receiver.attr = v`` takes: ``type(receiver).__delattr__(receiver,
    "attr")``.  A formal whose class is a class input here is the dispatched
    ``__delattr__``; a decided runtime type its floor's delete (never the
    read path -- readability never authorizes deletion); any other receiver,
    formal or not, the one undecided delete
    (``undecided_attribute_mutation_faces``), its halt kept.  No delete
    waits on a caller's actual.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)
    # The delete's halted face reached nothing inside this statement: the
    # reducer gives it the prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._delete(receiver, ctx)
        )

    def _delete(self, receiver, ctx) -> ExitSet:
        from sugar_lift_py_tests.sugar.store_effect_sugar import attribute_mutation

        return attribute_mutation(
            "__delattr__",
            receiver,
            self.attr,
            (),
            self.site,
            ctx,
            unit=getattr(self.site, "unit", None),
        )


@dataclass(frozen=True)
class SubscriptDeleteEffectSugar(Sugar):
    """`del receiver[index]` — evaluate once, then project the delete face.

    The delete itself is the one item mutation
    (``store_effect_sugar.item_mutation``), the same one ``r[k] = v`` and
    the container-mutation door's ``__delitem__`` take.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)
    # The delete's halted face reached nothing inside this statement: the
    # reducer gives it the prefix (``undecided_item_mutation_faces``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._delete(receiver, index, ctx)
            )
        )

    def _delete(self, receiver, index, ctx) -> ExitSet:
        from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

        return item_mutation(
            "__delitem__",
            receiver,
            (index,),
            self.site,
            ctx,
            unit=getattr(self.site, "unit", None),
        )
