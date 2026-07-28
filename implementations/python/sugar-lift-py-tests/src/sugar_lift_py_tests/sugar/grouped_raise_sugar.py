"""Authenticated ``ExceptionGroup`` tree construction for ``except*`` routing.

Produces an immutable ``GroupedRaiseEffect`` whose leaves are ordinary
``RaiseEffect`` values (authenticated type coordinate, MRO, occurrence). Nested
groups stay nested: children are never flattened. Spelling does not grant
group authority — only the Raise construction path that recognized the builtin
group coordinate may mint this sugar.

Group occurrence identity is the sealed source fragment CID (content-addressed),
never a fabricated ``filename:line:col`` string — identical positions in
different authenticated sources must differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def sealed_source_occurrence(site, *, owner: str) -> str:
    """Sealed source occurrence coordinate for this construction site.

    Uses the full sealed memento (file + source_cid + span + segment cid), not
    a fabricated ``filename:line:col`` spelling. Identical positions in
    different authenticated sources differ via ``file`` / ``source_cid``.
    """
    from sugar_source_tree.panic import SugarNotWritten

    seal = getattr(site, "seal", None)
    if seal is None:
        raise SugarNotWritten(
            blame=site,
            owner=owner,
            observed="group construction site lacks seal()",
            requested="a sealed SourceFragment occurrence coordinate",
            fix="construct GroupedRaiseSugar only from an enumerated source fragment",
        )
    memento = seal()
    cid = getattr(memento, "cid", None)
    source_cid = getattr(memento, "source_cid", None)
    file = getattr(memento, "file", None)
    start = getattr(memento, "start", None)
    end = getattr(memento, "end", None)
    if not cid or not source_cid or file is None or start is None or end is None:
        raise SugarNotWritten(
            blame=site,
            owner=owner,
            observed=type(memento).__name__,
            requested="SourceMemento{file,start,end,source_cid,cid}",
            fix="seal the raise site before minting GroupedRaiseEffect.occurrence",
        )
    # Full sealed coordinate — content CID alone collides across files that
    # share identical span text; file + source_cid pin the authenticated source.
    return f"{file}:{start}:{end}:{source_cid}:{cid}"


@dataclass(frozen=True)
class GroupedRaiseSugar(Sugar):
    """Construct one authenticated exception-group tree without flattening it."""

    group_identity: str
    message: Sugar
    children: tuple[Sugar, ...]
    site: object = dataclass_field(compare=False)

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
        occurrence = sealed_source_occurrence(
            self.site, owner="GroupedRaiseSugar.desugar"
        )
        return Incomplete(
            GroupedRaiseEffect(
                self.group_identity,
                message.value,
                tuple(effects),
                occurrence=occurrence,
            )
        )
