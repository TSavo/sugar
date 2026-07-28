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
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
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

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_source_tree.panic import SugarNotWritten

        message = self.message.desugar(ctx)
        if not isinstance(message, Complete):
            return message
        effects = []
        for child in self.children:
            outcome = child.desugar(ctx)
            if not isinstance(outcome, Incomplete) or not isinstance(
                outcome.effect, (RaiseEffect, GroupedRaiseEffect)
            ):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="GroupedRaiseSugar.desugar",
                    observed=type(outcome).__name__,
                    requested="a constructed raise effect for every group child",
                    fix="keep non-exception group members loud",
                )
            effects.append(outcome.effect)
        # Typed door: site is SourceFragment; seal() returns SourceMemento.
        memento = self.site.seal()
        # Full sealed coordinate — segment cid alone collides across files that
        # share identical span text; file + source_cid pin the authenticated source.
        occurrence = (
            f"{memento.file}:{memento.start}:{memento.end}"
            f":{memento.source_cid}:{memento.cid}"
        )
        return Incomplete(
            GroupedRaiseEffect(
                self.group_identity,
                message.value,
                tuple(effects),
                occurrence=occurrence,
            )
        )
