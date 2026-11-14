"""Authenticated ``ExceptionGroup`` tree construction for ``except*`` routing.

Produces an immutable ``GroupedRaiseEffect`` whose leaves are the effects their
own raises would halt with: a ``RaiseEffect`` (type coordinate, MRO,
occurrence) read off the value each member's construction made, or an
``UndeterminedRaiseEffect`` where that construction carries no class. Nested
groups stay nested: children are never flattened. Spelling does not grant
group authority — only the Raise construction path that recognized the builtin
group coordinate may mint this sugar.

Group occurrence identity is the sealed ``SourceMemento`` from the typed
``SourceFragment`` construction door — never a fabricated ``filename:line:col``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import GroupedRaiseEffect
from sugar_lift_py_tests.outcome import ExitSet
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

    def constructed(self, ctx: object = None) -> ExitSet:
        """The group this raise builds, without raising it: what an enclosing
        group holds as its member, and what ``desugar`` raises.

        The message, then each member in order, is constructed.  A member's
        construction that halts (``OSError(e, 'x')`` may raise before any
        group exists) halts the whole raise; it is never a member.  Each
        completed arm of a member's construction is the member's effect
        (``RaiseSugar.constructed``), whose class was read off the value the
        member's construction made -- undetermined where that construction
        is unanswered, never the callee's.  ``sequence`` carries every arm's
        guard, faces and ``owed`` onto the group built beneath it, so what a
        member's construction owes, the group owes."""

        def build(message_value):
            members = ExitSet.completed(())
            for child in self.children:
                members = members.sequence(
                    lambda effects, child=child: child.constructed(ctx).and_then(
                        lambda member, effects=effects: ExitSet.completed(
                            (*effects, member)
                        )
                    )
                )
            # Typed door: site is SourceFragment; seal() returns SourceMemento.
            memento = self.site.seal()
            # Full sealed coordinate — segment cid alone collides across files
            # that share identical span text; file + source_cid pin the
            # authenticated source.
            occurrence = (
                f"{memento.file}:{memento.start}:{memento.end}"
                f":{memento.source_cid}:{memento.cid}"
            )
            return members.sequence(
                lambda effects: ExitSet.completed(
                    GroupedRaiseEffect(
                        self.group_identity,
                        message_value,
                        tuple(effects),
                        occurrence=occurrence,
                        exception_type_coordinate=self.exception_type_coordinate,
                        exception_type_mro=self.exception_type_mro,
                    )
                )
            )

        return self.message.desugar(ctx).and_then(build)

    def desugar(self, ctx: object = None) -> ExitSet:
        """Raise the group ``constructed`` builds, on each arm it is built."""
        return self.constructed(ctx).and_then(lambda group: ExitSet.halted(group))
