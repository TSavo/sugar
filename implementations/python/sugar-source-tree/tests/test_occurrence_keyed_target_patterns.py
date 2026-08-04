"""Red teeth for #7346-A: the target-pattern relation is keyed by OCCURRENCE.

The defect these teeth pin: the relation was keyed by the consumer's ``Node``
ref.  ``shadow.rewrite`` mints a FRESH ref for the rewritten consumer, so every
substitution that changed a comprehension stranded its own producer row -- and
the row went missing as a plausible EMPTY, not as a failed join.

``ListComp`` alone was protected, by a ``retain_target_patterns`` call added
reactively in 038c435cba when someone hit that case in the wild.  ``SetComp``,
``DictComp`` and ``GeneratorExp`` are equally enrolled consumers that equally
mint a new parent ref, and none of them retained.  That asymmetry is the whole
evidence that a per-consumer obligation nobody can enforce is the wrong shape:
one consumer was remembered and three were forgotten, and nothing failed loudly
when the next one was added.

The repair is not a fourth retention call.  ``shadow.rewrite`` deliberately
borrows the origin's span and keeps its kind and unit, so the rewrite denotes
the SAME ``SourceOccurrenceIdentityV1`` as its origin while the ref does not.
Keying the relation on the occurrence makes retention unnecessary for all four
consumers at once, with no obligation for anyone to remember.

Each test below is one tooth: a rewritten destructuring comprehension of each
kind must still join its producer-minted pattern.  ``ListComp`` is the control
-- at the pre-repair pin it passes (it had retention) while the other three
fail, which is what makes the failure a keying defect rather than a broken
fixture.

#7364 trap: SourceUnits are memoized by (source_cid, workspace-relative
filename), so byte-identical fixtures SHARE ONE UNIT and a distinct tmp_path
buys ZERO isolation.  Every fixture below is given unique source text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree import nodes, occurrence
from sugar_source_tree.reporter import NULL_REPORTER
from sugar_source_tree.tree import SourceFile


# Each fixture destructures ``(left, right)`` out of a FREE name, so the
# comprehension is an enrolled target-pattern consumer whose ``iter`` really
# changes under substitution.  The replacement is another free Name, never a
# concrete display: a concrete iterable would unroll to a display and the
# rewrite path under test would never be taken.
_SHAPES = {
    "listcomp": "[left_{tag} for (left_{tag}, right_{tag}) in seed_{tag}]",
    "setcomp": "{{left_{tag} for (left_{tag}, right_{tag}) in seed_{tag}}}",
    "dictcomp": "{{left_{tag}: right_{tag} for (left_{tag}, right_{tag}) in seed_{tag}}}",
    "generatorexp": "(left_{tag} for (left_{tag}, right_{tag}) in seed_{tag})",
}

_KINDS = {
    "listcomp": "ListComp",
    "setcomp": "SetComp",
    "dictcomp": "DictComp",
    "generatorexp": "GeneratorExp",
}


def _source(shape: str) -> str:
    tag = shape
    body = _SHAPES[shape].format(tag=tag)
    # Unique text per shape AND per kind name, so no two fixtures in this file
    # -- or in any neighbouring file -- can collide on one memoized SourceUnit.
    return (
        f"def fixture_{tag}(seed_{tag}, alt_{tag}):\n"
        # A real load occurrence of ``alt_*``: a parameter is not a Name node,
        # and the substitution value has to be an actual Node from this unit.
        f"    keep_{tag} = alt_{tag}\n"
        f"    return {body}\n"
    )


def _open(tmp_path: Path, shape: str) -> SourceFile:
    text = _source(shape)
    path = tmp_path / f"occ_{shape}.py"
    path.write_text(text)
    from sugar_lift_python_source.source_oracle import workspace_path_source

    return SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)), reporter=NULL_REPORTER
    )


def _comprehension(source_file: SourceFile, shape: str):
    kind = _KINDS[shape]
    return next(node for node in source_file.nodes() if node.kind == kind)


def _free_name(source_file: SourceFile, shape: str):
    """The ``alt_*`` parameter, used as a non-concrete substitution value."""
    return next(
        node
        for node in source_file.nodes()
        if node.kind == "Name" and node.id == f"alt_{shape}"
    )


def _rewritten(source_file: SourceFile, shape: str):
    """Substitute the comprehension's iterable, forcing a real shadow rewrite."""
    comprehension = _comprehension(source_file, shape)
    replacement = _free_name(source_file, shape)
    rewritten = comprehension.substitute({f"seed_{shape}": replacement})
    assert rewritten is not comprehension, "fixture did not exercise the rewrite path"
    assert rewritten.kind == _KINDS[shape]
    # The precondition the whole issue turns on: the rewrite is a NEW ref, so a
    # ref-keyed relation loses it, while the occurrence is unchanged.
    assert rewritten.ref is not comprehension.ref
    assert occurrence.SourceOccurrenceIdentityV1.of(
        rewritten
    ) == occurrence.SourceOccurrenceIdentityV1.of(comprehension)
    return comprehension, rewritten


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_rewritten_destructuring_comprehension_retains_its_pattern(
    shape, tmp_path: Path
) -> None:
    """TOOTH -- all four consumers, no retention call anywhere."""
    source_file = _open(tmp_path, shape)
    origin, rewritten = _rewritten(source_file, shape)

    # Precondition: the origin really owns a producer-minted row.
    (origin_pattern,) = origin.require_target_patterns()

    # The claim: the rewrite joins the SAME row, with no per-consumer retention.
    (rewritten_pattern,) = rewritten.require_target_patterns()
    assert rewritten_pattern is origin_pattern

    # And the pair-exact doors join too, read through the REWRITE as consumer.
    # (The target child itself is carried through the rewrite unchanged; it is
    # the CONSUMER's ref that moves, which is exactly what stranded the row.)
    rewritten_target = rewritten.generators[0].target
    assert (
        source_file.unit.require_target_pattern(rewritten, rewritten_target)
        is origin_pattern
    )
    assert (
        source_file.unit.require_target_pattern_for_target(rewritten_target)
        is origin_pattern
    )


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_rewritten_consumer_stays_enrolled_and_a_stranded_row_still_refuses(
    shape, tmp_path: Path
) -> None:
    """The OTHER arm: keying by occurrence must not soften any refusal.

    Absence and lookup-failure still have separate representations.  Dropping
    the row keeps the enrollment answer TRUE and makes the lookup scream --
    exactly as it did when the relation was ref-keyed.
    """
    source_file = _open(tmp_path, shape)
    _origin, rewritten = _rewritten(source_file, shape)
    unit = source_file.unit

    assert isinstance(
        rewritten.target_pattern_enrollment, nodes.TargetPatternEnrolledV1
    )

    # Bypass the mechanism: drop the row the rewrite would have joined.
    unit._target_patterns_by_consumer.pop(
        occurrence.SourceOccurrenceIdentityV1.of(rewritten)
    )

    # Enrollment is UNCHANGED by a lost row: it is not read out of the relation.
    assert isinstance(
        rewritten.target_pattern_enrollment, nodes.TargetPatternEnrolledV1
    )
    with pytest.raises(nodes.TargetPatternConstructionGapV1) as stranded:
        rewritten.require_target_patterns()
    assert stranded.value.reason == "foreign-target-occurrence"


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_foreign_units_occurrence_never_joins_this_units_relation(
    shape, tmp_path: Path
) -> None:
    """Occurrence keying must not become a span-only or name-only match.

    A twin file with the SAME span and the SAME node kind is a DIFFERENT
    occurrence, because the pinned source differs.  It must refuse, not join.
    """
    source_file = _open(tmp_path, shape)
    origin = _comprehension(source_file, shape)

    # A twin whose text differs only in a trailing comment: the comprehension
    # keeps its exact span and kind, and only the source CID moves.
    twin_text = _source(shape) + "# a different authenticated source\n"
    twin_path = tmp_path / f"occ_{shape}_twin.py"
    twin_path.write_text(twin_text)
    from sugar_lift_python_source.source_oracle import workspace_path_source

    twin = SourceFile(
        workspace_path_source(str(twin_path), root=str(tmp_path)),
        reporter=NULL_REPORTER,
    )
    twin_comprehension = _comprehension(twin, shape)

    origin_occurrence = occurrence.SourceOccurrenceIdentityV1.of(origin)
    twin_occurrence = occurrence.SourceOccurrenceIdentityV1.of(twin_comprehension)
    assert (origin_occurrence.start, origin_occurrence.end) == (
        twin_occurrence.start,
        twin_occurrence.end,
    )
    assert origin_occurrence.node_kind == twin_occurrence.node_kind
    assert origin_occurrence != twin_occurrence

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as foreign:
        source_file.unit.require_target_pattern(
            twin_comprehension, twin_comprehension.generators[0].target
        )
    assert foreign.value.reason == "foreign-target-occurrence"
