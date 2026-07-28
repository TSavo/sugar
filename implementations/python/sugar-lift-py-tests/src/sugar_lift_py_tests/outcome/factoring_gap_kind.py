"""Split `R(factoring_gaps)` into remaining work and correct output (#6356).

`factoring_gaps` is one number covering two different things:

  (a) a producer OWNED a partition and failed to carry the testimony -- real,
      closable work, exactly what #6336 was built for;
  (b) a refusal of arms with no exclusion available -- correct output, and
      `factor_completed` doing its job.

Nothing separated them, so the term could not be read either way: under a
"wire the producers" plan you need (a) to size the design, under an "accept the
residual" plan you need it to name an owner, and under a "stop counting correct
refusals" plan you need it to define what stops being counted. The split is
common to all three.

This is the same move that made `R_desugar` legible. That figure was a mixed
number until it was split off the authenticated occurrence-key prefix, and the
owed work turned out to be a fraction of the total. A term that mixes correct
output with remaining work overstates the board.

THE CHANNEL IS CARRIED TESTIMONY, NOT GUARD SHAPE. `PartitionFace` is what a
producer SAID when it split; guard spelling is a downstream artefact that a
conjunction, a merge or a rewrite can change without changing the meaning.
#6356 established the hard way that shape is the wrong channel here: a
conjunctive prefix does not hide an exclusion (`_conjuncts` flattens), and the
shape that does hide one -- a disjunction from an equal-destination merge -- is
exactly where #6336's rule has already intersected the testimony away.

NAMING IS LOAD-BEARING. `_are_exclusive` is SOUND-ONLY: `False` means "not
proven", never "proven false". So no classification here may be called
"overlapping". `NO_EXCLUSION_AVAILABLE` says precisely what was observed --
this prover, on this evidence, has nothing to separate these arms -- and
claims nothing about whether they can actually both hold.

This module CHANGES NO BEHAVIOUR. The refusal fires identically in every class.
It only reads the arms a refusal already carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FactoringGapKind(Enum):
    """Why one refusal happened, read off the arms' carried testimony."""

    UNSTAMPED = "unstamped"
    """Neither arm carries a face. NO producer testified at all.

    Remaining work IF a producer here owns a split -- and that is a real IF,
    not a promise. #6361 measured one occurrence where wiring the producer
    changed nothing, because an arm was merged and the testimony would have
    been intersected away before it arrived. `merged_arm` below is what
    separates the hopeful case from that one.
    """

    STAMPED_NOT_SEPARATING = "stamped-not-separating"
    """Both arms carry faces and share a partition, never on opposite sides.

    Testimony WAS offered and does not separate these two. Wiring more
    producers cannot help: the producers that own these arms have already
    spoken.
    """

    STAMPED_DISJOINT = "stamped-disjoint"
    """Both arms carry faces, sharing no partition at all.

    They come from unrelated splits, so neither producer ever claimed anything
    about the other. Not a wiring omission and not a lie -- simply two arms
    about which nothing exclusive was ever said.
    """

    PARTLY_STAMPED = "partly-stamped"
    """One arm testifies, the other does not. The silent side is the lead."""


@dataclass(frozen=True)
class FactoringGapClassification:
    kind: FactoringGapKind
    merged_arm: bool
    """At least one arm's guard carries a disjunction at conjunct level.

    STRUCTURAL, and named apart from `kind` on purpose: this is the one thing
    here read off guard SHAPE rather than testimony, and it is not used to
    decide exclusivity. It detects that an equal-destination merge happened,
    because `_or_guards` is the only thing that puts a disjunction there.

    It matters because #6336's composition rule INTERSECTS faces on such a
    merge -- correctly, since a merged arm holds under a disjunction and may
    only keep what every contributing arm carried. So an `UNSTAMPED` gap with
    `merged_arm=True` will NOT be closed by wiring its producer: the face would
    be minted and then intersected away. #6361 measured exactly that.

    `UNSTAMPED` and not merged is the shape actually worth trying.
    """

    left_owner: str
    right_owner: str

    @property
    def is_remaining_work(self) -> bool:
        """Whether wiring a producer could plausibly close this occurrence.

        Deliberately narrow. A stamped gap has already heard from its
        producers, and a merged arm cannot keep a new face. Everything else is
        `NO_EXCLUSION_AVAILABLE` for this prover -- which is NOT a claim that
        the arms overlap.
        """
        return (
            self.kind in (FactoringGapKind.UNSTAMPED, FactoringGapKind.PARTLY_STAMPED)
            and not self.merged_arm
        )

    def row(self) -> dict:
        return {
            "kind": self.kind.value,
            "mergedArm": self.merged_arm,
            "leftOwner": self.left_owner,
            "rightOwner": self.right_owner,
            "isRemainingWork": self.is_remaining_work,
        }


def _has_disjunct(guard) -> bool:
    from sugar_lift_py_tests.outcome.exit_set import _conjuncts

    return any(getattr(lit, "kind", None) == "or" for lit in _conjuncts(guard))


def classify_factoring_gap(left, right) -> FactoringGapClassification:
    """Classify ONE refusing pair of completed arms. Reads, never decides."""
    left_faces = frozenset(getattr(left, "faces", ()) or ())
    right_faces = frozenset(getattr(right, "faces", ()) or ())

    if not left_faces and not right_faces:
        kind = FactoringGapKind.UNSTAMPED
    elif not left_faces or not right_faces:
        kind = FactoringGapKind.PARTLY_STAMPED
    else:
        shared = {face.partition for face in left_faces} & {
            face.partition for face in right_faces
        }
        kind = (
            FactoringGapKind.STAMPED_NOT_SEPARATING
            if shared
            else FactoringGapKind.STAMPED_DISJOINT
        )

    return FactoringGapClassification(
        kind=kind,
        merged_arm=_has_disjunct(left.guard) or _has_disjunct(right.guard),
        left_owner=type(left.value).__name__,
        right_owner=type(right.value).__name__,
    )


__all__ = [
    "FactoringGapClassification",
    "FactoringGapKind",
    "classify_factoring_gap",
]
