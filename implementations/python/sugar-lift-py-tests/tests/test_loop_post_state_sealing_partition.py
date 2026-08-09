# SPDX-License-Identifier: MIT OR Apache-2.0
#
# A NAME CARRIED ACROSS TWO LOOPS. The second loop has to seal the first loop's
# post-state, and a loop that can `break` leaves more than one completed face.
#
# `live_loop_construction._seal_runtime_state` handled exactly one of those
# faces and refused the rest:
#
#     BindingStateWireGap: multi-face loop projected binding sealing is
#     unimplemented; stays loud rather than fold a multi-way completion join
#
# The refusal was right to exist. Folding n faces into nested
# `GuardedBindingStateV1` means picking an order and naming one face the
# else-branch, which asserts a fallthrough the producer never declared -- the
# same trap the same-type partition law refuses.
#
# THE MECHANISM IS TO SEAL THE FACES AS A PARTITION, not to fold them. Each
# face keeps the guard formula CID the producer minted and the arity it
# declared, keyed by the producer OCCURRENCE (`targetCid`) that minted them --
# two loops in one function are two occurrences and share no exclusion.
#
# `test_two_sequential_breaking_loops_construct` is the discrimination tooth:
# it raises `BindingStateWireGap` with the law removed and passes with it. Every
# other test here perturbs exactly one admission criterion and asserts refusal,
# so the end-to-end green cannot be bought by a permissive decoder.

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.loop_construction import LoopWireError, _decode_binding_entry
from sugar_source_tree.binding_provenance import (
    BindingProvenanceGap,
    LoopProjectedBindingStateV1,
    LoopProjectedFaceV1,
    _decode_state,
    _state_wire,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

_CID = "blake3-512:" + "ab" * 64
_CID2 = "blake3-512:" + "cd" * 64
_CID3 = "blake3-512:" + "ef" * 64

# The shape of `pandas/util/_exceptions.py:37` generalized: one name written by
# a loop that can `break`, then carried past it. Two sequential loops is the
# smallest source that forces the SECOND loop to seal the FIRST loop's
# multi-face post-state.
TWO_LOOPS = """\
def two_loops(xs, ys):
    v = 0
    for x in xs:
        v = v + x
        if x.stop:
            break
    for y in ys:
        v = v + y
        if y.stop:
            break
    del v
    return 1
"""


def _desugar_all(path: Path) -> None:
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    for function in SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions():
        sugar = function.sugar()
        if sugar is not None:
            sugar.desugar(None)


def _face(kind: str, *, state_cid: str = _CID2, arity: int | None = 2):
    return LoopProjectedFaceV1(kind, _CID3, state_cid, arity)


def _two_faces():
    return (_face("BreakExit"), _face("NormalExhaustion", state_cid=_CID))


# --------------------------------------------------------------------------
# end to end: the discrimination tooth
# --------------------------------------------------------------------------


def test_two_sequential_breaking_loops_construct(tmp_path):
    """POSITIVE, end to end. Raises `BindingStateWireGap` without the law.

    This is the reproducer the mechanism was built from, and it is the only
    test here that fails when the sealing arm is removed -- the rest are
    discriminators over the wire law.
    """
    path = tmp_path / "fixture.py"
    path.write_text(TWO_LOOPS)
    _desugar_all(path)


def test_one_face_loop_still_collapses_to_its_face(tmp_path):
    """A loop with no `break` exits only by exhaustion: still a direct seal.

    Pins that the new arm did not swallow the single-face path. A one-face
    projection is TOTAL, so it seals as its face's own state and mints no
    partition -- if this started producing a `loopProjected` wire, every
    existing single-face CID would have moved.
    """
    path = tmp_path / "fixture.py"
    path.write_text(
        "def one_loop(xs, ys):\n"
        "    v = 0\n"
        "    for x in xs:\n"
        "        v = v + x\n"
        "    for y in ys:\n"
        "        v = v + y\n"
        "    return v\n"
    )
    _desugar_all(path)


# --------------------------------------------------------------------------
# the sealed state is a partition, and it round-trips
# --------------------------------------------------------------------------


def test_wire_round_trips_and_keeps_arity_and_occurrence():
    state = LoopProjectedBindingStateV1(_CID, _two_faces())
    wire = _state_wire(state)
    assert wire["kind"] == "loopProjected"
    assert wire["targetCid"] == _CID
    assert [face["completionKind"] for face in wire["faces"]] == [
        "BreakExit",
        "NormalExhaustion",
    ]
    assert _decode_state(wire) == state


def test_arity_none_survives_the_wire():
    """A producer that never stated a family size is carried, not defaulted.

    `None` must stay `None`: inventing an arity here would let completeness be
    claimed downstream by a face whose producer never declared one.
    """
    state = LoopProjectedBindingStateV1(
        _CID, (_face("BreakExit", arity=None), _face("NormalExhaustion", arity=None))
    )
    wire = _state_wire(state)
    assert [face["exitPartitionArity"] for face in wire["faces"]] == [None, None]
    assert _decode_state(wire) == state


def test_two_occurrences_with_identical_faces_are_different_states():
    """The occurrence is load-bearing, not decoration.

    Two loops in one function mint two partitions that share no exclusion. If
    `targetCid` dropped out of the identity, the second loop's post-state would
    be indistinguishable from the first's.
    """
    faces = _two_faces()
    assert LoopProjectedBindingStateV1(_CID, faces) != LoopProjectedBindingStateV1(
        _CID2, faces
    )
    assert _state_wire(LoopProjectedBindingStateV1(_CID, faces)) != _state_wire(
        LoopProjectedBindingStateV1(_CID2, faces)
    )


# --------------------------------------------------------------------------
# lying twins: each perturbs exactly one admission criterion
# --------------------------------------------------------------------------


def test_no_faces_is_refused():
    with pytest.raises(BindingProvenanceGap, match="requires faces"):
        LoopProjectedBindingStateV1(_CID, ())


def test_repeated_completion_kind_is_refused():
    """One face per completion kind, or it is not a partition.

    Two `BreakExit` faces are two values claiming the same route -- exactly the
    same-type pair the partition law refuses to read as an exclusion.
    """
    with pytest.raises(BindingProvenanceGap, match="one per completion kind"):
        LoopProjectedBindingStateV1(_CID, (_face("BreakExit"), _face("BreakExit")))


def test_unsorted_faces_are_refused():
    """Canonical order, or the same partition has two CIDs."""
    with pytest.raises(BindingProvenanceGap, match="completion-kind sorted"):
        LoopProjectedBindingStateV1(
            _CID, (_face("NormalExhaustion"), _face("BreakExit"))
        )


@pytest.fixture(scope="module")
def coordinate_wire(tmp_path_factory):
    """One real minted coordinate, reused as the carrier for wire tests.

    The coordinate is not what these tests are about -- it has to be genuine
    only so the decoder reaches the `state` field it IS about.
    """
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.binding_provenance import BindingCoordinateV1
    from sugar_source_tree.tree import SourceFile

    path = tmp_path_factory.mktemp("coord") / "fixture.py"
    path.write_text("def f(v):\n    return v\n")
    function = next(
        iter(
            SourceFile(
                path_source(str(path)),
                construction_context=TreeConstructionContextV1.for_test_without_workspace(),
            ).functions()
        )
    )
    return BindingCoordinateV1.mint(_CID, function.fragment, ("v",)).wire()


def _entry(coordinate_wire, state_wire):
    """A minimally valid entry carrying `state_wire`, for the wire decoder."""
    return {"coordinate": coordinate_wire, "state": state_wire}


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda w: w.update(faces=[]), "requires faces"),
        (
            lambda w: w["faces"][0].update(completionKind="LoopExit"),
            "unknown loop completion kind",
        ),
        (
            lambda w: w["faces"][0].update(completionKind="NormalExhaustion"),
            "one per completion kind",
        ),
        (lambda w: w["faces"][0].update(guardFormulaCid="nope"), "guardFormulaCid"),
        (lambda w: w["faces"][0].update(exitPartitionArity="2"), "exitPartitionArity"),
        (lambda w: w.update(targetCid="nope"), "targetCid"),
    ],
    ids=[
        "empty-faces",
        "unknown-completion-kind",
        "duplicate-completion-kind",
        "guard-cid-not-a-cid",
        "arity-not-an-int",
        "occurrence-not-a-cid",
    ],
)
def test_the_wire_decoder_refuses_each_perturbation(coordinate_wire, mutate, match):
    """The loop wire is a second decoder, and it must refuse the same things.

    `loop_construction._decode_binding_entry` validates the sealed wire
    independently of the dataclass. A permissive decoder here would let a
    malformed partition through the seal even though the constructor refuses it,
    so every criterion is asserted on both sides.
    """
    wire = _state_wire(LoopProjectedBindingStateV1(_CID, _two_faces()))
    mutate(wire)
    with pytest.raises(LoopWireError, match=match):
        _decode_binding_entry(_entry(coordinate_wire, wire))


def test_the_wire_decoder_accepts_the_unperturbed_partition(coordinate_wire):
    """Positive control for the refusals above.

    Every test in the block above asserts a raise. Without this one, a decoder
    that refused EVERY `loopProjected` wire would pass all of them.
    """
    wire = _state_wire(LoopProjectedBindingStateV1(_CID, _two_faces()))
    coordinate_cid, decoded = _decode_binding_entry(_entry(coordinate_wire, wire))
    assert decoded["state"] == wire
    assert coordinate_cid
