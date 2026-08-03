"""Focused owner-first instrument for Halted lineage seating (test-only)."""

from __future__ import annotations

import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

import sugar_lift_py_tests.outcome.exit_set as owner
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset


def _reduce(tmp_path: Path, stem: str, text: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(text, encoding="utf-8")
    source = open_source_file_for_construction(
        path,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(
            workspace_root=str(tmp_path)
        ),
    )
    (function,) = tuple(source.functions())
    return source, function, reduce_block_to_exitset(function.sugar().statements, None)


def test_raise_owner_seats_exact_paired_lineage(tmp_path: Path, monkeypatch):
    from sugar_lift_py_tests.sugar import exit_set_routing

    seen = []
    original = exit_set_routing.promote_raise_halts

    def observe(exits):
        seen.append(exits)
        return original(exits)

    monkeypatch.setattr(exit_set_routing, "promote_raise_halts", observe)
    with pytest.raises(owner._HaltLineageProducerMissingV1):
        _reduce(tmp_path, "raise", "def target():\n    raise ValueError('x')\n")
    assert len(seen) == 1


@pytest.mark.parametrize("statement", ["break", "continue"])
def test_loop_control_owner_seats_authenticated_nonraise(
    tmp_path: Path, statement: str, monkeypatch
):
    from sugar_lift_py_tests.sugar.loop_control_sugar import LoopControlSugar

    seen = []
    original = LoopControlSugar.desugar

    def observe(self, ctx=None):
        seen.append((self, ctx))
        return original(self, ctx)

    monkeypatch.setattr(LoopControlSugar, "desugar", observe)
    with pytest.raises(owner._HaltLineageProducerMissingV1):
        _reduce(
            tmp_path,
            statement,
            f"def target(xs):\n    for x in xs:\n        {statement}\n",
        )
    assert len(seen) == 1
    assert seen[0][0].target_cid != seen[0][0].occurrence_cid


def test_legacy_and_forged_faces_refuse_with_external_zero_work(tmp_path: Path):
    pytest.importorskip("sugar_lift_py_tests.outcome.exit_set")
    source, _, exits = _reduce(
        tmp_path, "plain", "def target():\n    raise ValueError('x')\n"
    )
    (face,) = exits.exits
    refusal_type = owner._HaltLineageRefusalV1
    for operation in (
        lambda: type(face)(face.guard, face.effect, face.state),
        lambda: copy.copy(face),
        lambda: copy.deepcopy(face),
        lambda: dataclasses.replace(face, effect=face.effect),
        lambda: pickle.loads(pickle.dumps(face)),
    ):
        with pytest.raises(refusal_type) as raised:
            operation()
        assert raised.value.effect is face.effect
        assert raised.value.context is face.state.context
        assert raised.value.source is source.unit
        assert raised.value.occurrence == face.effect.occurrence_id
        assert raised.value.downstream_work == 0


def test_transforms_preserve_identity_and_cross_variant_refuses(tmp_path: Path):
    _, _, exits = _reduce(
        tmp_path, "transform", "def target():\n    raise ValueError('x')\n"
    )
    (face,) = exits.exits
    lineage = owner._read_halt_lineage(face)
    (guarded,) = owner.ExitSet((face,)).guarded(face.guard).exits
    (normalized,) = owner.ExitSet((face,)).normalize().exits
    assert owner._read_halt_lineage(guarded) is lineage
    assert owner._read_halt_lineage(normalized) is lineage
