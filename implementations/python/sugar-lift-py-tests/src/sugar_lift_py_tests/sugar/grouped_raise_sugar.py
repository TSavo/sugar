"""Authenticated ``ExceptionGroup`` tree construction for ``except*`` routing.

Produces an immutable ``GroupedRaiseEffect`` whose leaves are ordinary
``RaiseEffect`` values (authenticated type coordinate, MRO, occurrence). Nested
groups stay nested: children are never flattened. Spelling does not grant
group authority — only the Raise construction path that recognized the builtin
group coordinate may mint this sugar.

Group occurrence identity is the sealed ``SourceMemento`` from the typed
``SourceFragment`` construction door — never a fabricated ``filename:line:col``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
from sugar_lift_py_tests.outcome import ExitSet, Halted, Outcome, true_guard
from sugar_lift_py_tests.outcome.exit_set import owed_union
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.fragment import SourceFragment


@dataclass(frozen=True)
class GroupedRaiseSugar(Sugar):
    """Construct one authenticated exception-group tree without flattening it.

    Construction door: ``site`` is a typed ``SourceFragment``. The producer
    (Raise → GroupedRaiseSugar) must pass an enumerated fragment; there is no
    runtime kind-admission membrane over seal/memento.
    """

    group_identity: str
    message: Sugar
    children: tuple[Sugar, ...]
    site: SourceFragment = dataclass_field(compare=False)
    exception_type_coordinate: object | None = None
    exception_type_mro: tuple | None = None

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )
        from sugar_source_tree.panic import SugarNotWritten

        message = self.message.desugar(ctx)
        message_value = plain_completed_value(message)
        if message_value is None:
            return message
        effects = []
        owed = ()
        for child in self.children:
            outcome = child.desugar(ctx)
            halts = outcome.halts() if isinstance(outcome, ExitSet) else ()
            if (
                len(halts) != 1
                or halts != outcome.exits
                or halts[0].guard != true_guard()
                or not isinstance(halts[0].effect, (RaiseEffect, GroupedRaiseEffect))
            ):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="GroupedRaiseSugar.desugar",
                    observed=type(outcome).__name__,
                    requested="a constructed raise effect for every group child",
                    fix="keep non-exception group members loud",
                )
            effects.append(halts[0].effect)
            # What the child's halt owes, the group's halt owes.
            owed = owed_union(owed, halts[0].owed)
        # Typed door: site is SourceFragment; seal() returns SourceMemento.
        memento = self.site.seal()
        # Full sealed coordinate — segment cid alone collides across files that
        # share identical span text; file + source_cid pin the authenticated source.
        occurrence = (
            f"{memento.file}:{memento.start}:{memento.end}"
            f":{memento.source_cid}:{memento.cid}"
        )
        effect = GroupedRaiseEffect(
            self.group_identity,
            message_value,
            tuple(effects),
            occurrence=occurrence,
            exception_type_coordinate=self.exception_type_coordinate,
            exception_type_mro=self.exception_type_mro,
        )
        return ExitSet((Halted(true_guard(), effect, owed=owed),)).normalize()
