"""Two-axis honest-red instrument for the Halted lineage owner."""

from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

import sugar_lift_py_tests.outcome.exit_set as owner
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_source_tree.tree import SourceFile


DEPENDENT_AXIS_STATUS = {
    "migration_direct43_indirect20": "UNMEASURED: paired lineage door",
    "effect_change_same_event": "UNMEASURED: paired lineage door",
    "merge_same_and_distinct": "UNMEASURED: paired lineage door",
    "handler_match_bind_counters": "UNMEASURED: paired lineage door",
    "trystar_partition_substitution": "UNMEASURED: paired lineage door",
    "public_capability_closure": "UNMEASURED: paired lineage door",
    "constructor_copy_refusal_work0": "UNMEASURED: paired lineage door",
}


def _paired_gate(axis: str, tmp_path: Path | None = None):
    if tmp_path is not None:
        source, function, exits = _reduced(tmp_path, f"gate_{axis}", "def target():\n    raise ValueError('gate')\n")
        (face,) = exits.exits
        lineage = owner._read_halt_lineage(face)
        assert type(lineage) is owner._PairedRaiseFaceV1
        assert lineage.effect is face.effect
        assert lineage.pre_effect_context is face.state.context
        assert lineage.source_identity is source.unit
        assert lineage.definition_locus is function.fragment
        assert lineage.owner_receipt.source_identity is source.unit
    return True


def _reduced(tmp_path: Path, stem: str, text: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(text, encoding="utf-8")
    source = SourceFile.from_path(path)
    functions = tuple(source.functions())
    (function,) = functions
    return source, function, reduce_block_to_exitset(function.sugar().statements, None)


def _read(face):
    """Ordinary producer reduction is the sole admission boundary."""
    return owner._read_halt_lineage(face)


def test_paired_lineage_owner_and_all_downstream_teeth(tmp_path: Path):
    source, function, exits = _reduced(
        tmp_path, "paired", "def target():\n    raise ValueError('boom')\n"
    )
    (face,) = exits.exits
    assert isinstance(face.effect, RaiseEffect)
    lineage = _read(face)
    assert type(lineage) is owner._PairedRaiseFaceV1
    assert lineage.effect is face.effect
    assert lineage.pre_effect_context is face.state.context
    assert lineage.source_identity is source.unit
    assert lineage.definition_locus is function.fragment
    assert lineage.effect_occurrence == face.effect.occurrence_id
    assert lineage.owner_receipt.source_identity is source.unit

    (guarded,) = owner.ExitSet((face,)).guarded(face.guard).exits
    (normalized,) = owner.ExitSet((face,)).normalize().exits
    sequenced = owner.ExitSet((face,)).sequence(lambda value: owner.ExitSet.completed(value))
    assert _read(guarded) is lineage
    assert _read(normalized) is lineage
    (sequenced_face,) = sequenced.exits
    (merged_same,) = owner.ExitSet((face, face)).normalize().exits
    assert _read(sequenced_face) is lineage
    assert _read(merged_same) is lineage

    _, _, distinct_exits = _reduced(
        tmp_path, "distinct", "def target():\n    raise KeyError('boom')\n"
    )
    (distinct,) = distinct_exits.exits
    with pytest.raises(owner._HaltLineageConflictV1) as conflict:
        owner.ExitSet((face, distinct)).normalize()
    assert conflict.value.left_lineage is lineage
    assert conflict.value.right_lineage is _read(distinct)


    # Closed construction/refusal and public capability closure auto-activate
    # with the owner product; no test-only replay/mutation API is introduced.
    for operation in (
        lambda: type(face)(face.guard, face.effect, face.state),
        lambda: copy.copy(face),
        lambda: copy.deepcopy(face),
        lambda: dataclasses.replace(face, effect=face.effect),
        lambda: pickle.loads(pickle.dumps(face)),
    ):
        with pytest.raises(owner._HaltLineageRefusalV1) as refusal:
            operation()
        assert refusal.value.effect is face.effect
        assert refusal.value.context is face.state.context
        assert refusal.value.source is source.unit
        assert refusal.value.occurrence == face.effect.occurrence_id


    # Real TryStar path: partition lineage retains distinct authenticated
    # original/matched/residual occurrence objects.
    star_source, _, star_exits = _reduced(
        tmp_path,
        "star",
        "def target():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError('v'), TypeError('t')])\n"
        "    except* ValueError:\n"
        "        raise RuntimeError('handler')\n",
    )
    grouped = tuple(face for face in star_exits.exits if isinstance(face.effect, GroupedRaiseEffect))
    (grouped_face,) = grouped
    partition = _read(grouped_face).partition_lineage
    assert partition.source_identity is star_source.unit
    assert partition.original_occurrence is not partition.matched_occurrence
    assert partition.original_occurrence is not partition.residual_occurrence
    assert partition.matched_occurrence is not partition.residual_occurrence


def test_authenticated_nonraise_producer_and_cross_variant_refusal(tmp_path: Path):
    # This is an independent producer door: it must not key off the paired
    # reader.  Missing producer testimony is the sole honest red for this axis.
    variant_name = "_AuthenticatedNonRaiseHaltV1"
    if variant_name not in owner.__dict__:
        pytest.fail(
        "R_missing_authenticated_nonraise_producer=1: no canonical ordinary "
            "authenticated nonraise producer is available; do not fabricate one",
            pytrace=False,
        )
    pytest.fail(
        "R_missing_authenticated_nonraise_producer=1: canonical ordinary "
        "nonraise Halted specimen is unavailable; no fabricated Returned fixture",
        pytrace=False,
    )


def _semantic_raise(tmp_path: Path, stem: str = "semantic"):
    source, function, exits = _reduced(
        tmp_path, stem, "def target():\n    raise ValueError('ordinary')\n"
    )
    (face,) = exits.exits
    assert isinstance(face.effect, RaiseEffect)
    return source, function, face


def test_migration_and_transform_closure_is_producer_owned(tmp_path: Path):
    if not _paired_gate("migration_direct43_indirect20", tmp_path):
        return
    source, function, face = _semantic_raise(tmp_path, "migration")
    lineage = _read(face)
    assert lineage.source_identity is source.unit
    assert lineage.definition_locus is function.fragment


def test_effect_change_and_merge_laws_are_ordinary(tmp_path: Path):
    if not _paired_gate("effect_change_same_event", tmp_path):
        return
    if not _paired_gate("merge_same_and_distinct", tmp_path):
        return
    source, _, face = _semantic_raise(tmp_path, "effect_change")
    lineage = _read(face)
    changed = owner.ExitSet((face,)).normalize()
    (same,) = changed.exits
    assert _read(same) is lineage
    _, _, other = _semantic_raise(tmp_path, "merge_conflict")
    with pytest.raises(owner._HaltLineageConflictV1):
        owner.ExitSet((face, other)).normalize()


def test_handler_matching_binding_has_external_work_counters(tmp_path: Path):
    if not _paired_gate("handler_match_bind_counters", tmp_path):
        return
    source, function, exits = _reduced(
        tmp_path, "handler", "def target():\n    try:\n        raise ValueError('x')\n    except ValueError as error:\n        raise RuntimeError(str(error))\n    finally:\n        pass\n"
    )
    (face,) = exits.exits
    assert face.effect is not None
    assert source.unit is not None and function.fragment is not None


def test_trystar_partition_refusal_is_typed_and_observed(tmp_path: Path):
    if not _paired_gate("trystar_partition_substitution", tmp_path):
        return
    source, _, exits = _reduced(
        tmp_path, "partition", "def target():\n    try:\n        raise ExceptionGroup('g', [ValueError('v'), TypeError('t')])\n    except* ValueError:\n        raise RuntimeError('handled')\n"
    )
    grouped = tuple(f for f in exits.exits if isinstance(f.effect, GroupedRaiseEffect))
    (face,) = grouped
    partition = _read(face).partition_lineage
    assert partition.source_identity is source.unit
    assert partition.original_occurrence is not partition.matched_occurrence


def test_public_capability_closure_is_semantic():
    if not _paired_gate("public_capability_closure"):
        return
    raise AssertionError("semantic capability closure requires authenticated audit")


def test_closed_constructor_refusal_has_external_observation(tmp_path: Path):
    if not _paired_gate("constructor_copy_refusal_work0", tmp_path):
        return
    _, _, face = _semantic_raise(tmp_path, "refusal")
    with pytest.raises(owner._HaltLineageRefusalV1):
        type(face)(face.guard, face.effect, face.state)
