"""The loop names its own exit routes, and the read stamps them. Or the gap stays loud.

#6356 gave a producer the vocabulary for an n-way split. Two measured rows kept
using it as evidence they could not reach:

    core/methods/selectn.py:224   factoring_gaps=1  remaining_work=1
    core/indexing.py:2457         factoring_gaps=1  remaining_work=1

They are the SAME row twice. One arm is guarded by branch results (a `break`
was taken), the other by `python.loop.exhausted` (the loop ran to completion),
both are `merged=False`, and both are same-type pairs -- exactly the trap the
same-type partition law refuses to treat as an admission.

THE RULING, and this file is where it becomes executable at the CARRIER rather
than at the algebra:

  MINT A TWO-FACE PARTITION OVER `{BreakExit, NormalExhaustion}`.
  LEAVE `BodyFallthrough` UNSTAMPED.

`BodyFallthrough` is the LATCH input -- `loop_construction.py` requires the
latch obligation's input face to be exactly that kind -- so it is the loop-back
edge, not an exit route. Stamping it as a third exit face asserts an exclusion
nobody established.

THE CARRIER WAS MEASURED, NOT ASSUMED. The previous owner explicitly did not
establish it: the arms reach `factor_completed` through `store_effect_sugar` /
`method_call._collect` with NO `read_binding` frame anywhere in the stack, and
a `loop.exhausted` guard proves the loop OWNS the guard, not that any particular
carrier delivered it. Instrumenting every `LoopGuardedProjection` consumer while
re-running `selectn.py:224` named the carrier outright: both refusing arms were
minted by `read_binding`'s `LoopGuardedProjection` branch reading the name
`indexer`, as `BreakExit` and `NormalExhaustion`. The frames are silent because
the `ExitSet` is built at the read and only REFUSES later, downstream.

`test_the_loop_exit_family_reaches_the_arms` is the end-to-end tooth: its
fixture is the shape of `selectn.py:224` reduced to seven lines, it raised
`ExitSetFactoringGap` with the same `SymbolicValue`/`SymbolicValue` owner pair
at `ed686ba48`, and it desugars clean here. Everything else in this file is a
discriminator: each one perturbs exactly one admission criterion and asserts the
family is refused, so the end-to-end green cannot be bought by a fallback.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
)
from sugar_lift_py_tests.sugar.binding_projection import (
    LoopGuardedCompletedFace,
    LoopGuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.delete_name_sugar import delete_binding
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import _loop_exit_faces
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import GuardedBindingReadSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

# The shape of `pandas/core/methods/selectn.py:224`: a name carried across a
# `for` loop that can `break`, then READ after the loop. The read is where the
# two exit faces become two completed arms of one ExitSet.
FIXTURE = """\
def compute(columns, seed, sink):
    indexer = seed
    for column in columns:
        indexer = indexer.append(column)
        if column.done:
            break
    sink.result = indexer.finish()
    return sink
"""

_CID = "blake3-512:" + "ab" * 32


@dataclass(frozen=True)
class _SealedSite:
    source_cid: str
    start: int
    end: int
    cid: str


@dataclass(frozen=True)
class _TermSite:
    coordinate: str

    def seal(self):
        return _SealedSite(
            source_cid="blake3-512:" + "11" * 32,
            start=1,
            end=2,
            cid=self.coordinate,
        )


def _face(kind: str, arity: int | None, *, guard: object = None):
    return LoopGuardedCompletedFace(kind, guard, object(), arity)


def _projection(faces, target_cid: str | None = _CID):
    return LoopGuardedProjection(tuple(faces), target_cid)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "fixture.py"
    path.write_text(source)
    return path


def _desugar_all(path: Path) -> None:
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    for function in SourceFile(path_source(str(path))).functions():
        sugar = function.sugar()
        if sugar is not None:
            sugar.desugar(None)


# --------------------------------------------------------------------------
# end to end: the producer speaks and the row closes
# --------------------------------------------------------------------------


def test_the_loop_exit_family_reaches_the_arms(tmp_path):
    """POSITIVE, end to end. Red at `ed686ba48`, green here.

    Nothing is stubbed: the real live loop producer mints the wire records, the
    real decoder validates them, the real projection carries the declared family
    size, and the real `read_binding` stamps the arms. If this goes red, the two
    measured rows are back.
    """
    _desugar_all(_write(tmp_path, FIXTURE))


def test_guarded_loop_read_is_a_constructed_term_with_exact_coordinates():
    """Truthful producer: the read carries its occurrence and loop testimony."""
    from sugar_lift_py_tests.ir import _term_content_cid, atomic

    read_site = _TermSite("blake3-512:" + "22" * 32)
    value_site = _TermSite("blake3-512:" + "33" * 32)
    projection = LoopGuardedProjection(
        (
            LoopGuardedCompletedFace(
                "BreakExit",
                atomic("break_guard", []),
                IntLiteralSugar(1, value_site),
                2,
            ),
            LoopGuardedCompletedFace(
                "NormalExhaustion",
                atomic("exhausted_guard", []),
                IntLiteralSugar(2, value_site),
                2,
            ),
        ),
        _CID,
    )
    read = GuardedBindingReadSugar("value", projection, read_site)

    assert isinstance(read, ConstructedTermSugar)
    authentic_cid = _term_content_cid(read.to_term(owner="guarded-loop-read-test"))

    foreign_target = GuardedBindingReadSugar(
        "value",
        LoopGuardedProjection(
            projection.completed_faces,
            "blake3-512:" + "cd" * 32,
        ),
        read_site,
    )
    foreign_occurrence = GuardedBindingReadSugar(
        "value",
        projection,
        _TermSite("blake3-512:" + "44" * 32),
    )

    assert (
        _term_content_cid(
            foreign_target.to_term(owner="guarded-loop-read-foreign-target")
        )
        != authentic_cid
    )
    assert (
        _term_content_cid(
            foreign_occurrence.to_term(owner="guarded-loop-read-foreign-occurrence")
        )
        != authentic_cid
    )

    missing_target = GuardedBindingReadSugar(
        "value",
        LoopGuardedProjection(projection.completed_faces, None),
        read_site,
    )
    missing_arity_faces = tuple(
        LoopGuardedCompletedFace(
            face.completion_kind,
            face.guard_formula,
            face.state,
            None,
        )
        for face in projection.completed_faces
    )
    missing_arity = GuardedBindingReadSugar(
        "value",
        LoopGuardedProjection(missing_arity_faces, _CID),
        read_site,
    )

    with pytest.raises(TypeError, match="authenticated target CID"):
        missing_target.to_term(owner="guarded-loop-read-missing-target")
    with pytest.raises(TypeError, match="exit-family arity"):
        missing_arity.to_term(owner="guarded-loop-read-missing-arity")


def test_the_carrier_is_the_loop_projection_read(tmp_path):
    """THE CARRIER, pinned where it was measured rather than where it raises.

    The refusal's stack names `store_effect_sugar` and `method_call._collect`
    and no `read_binding` at all, so an agent reading only the traceback would
    wire the testimony into the wrong producer. This test asserts the mint lands
    at `read_binding`'s `LoopGuardedProjection` branch, over the loop's own
    target CID, with exactly the two exit routes as its sides.
    """
    from sugar_lift_py_tests.sugar import guarded_binding_read_sugar as module

    seen: list[LoopGuardedProjection] = []
    original = module._read_loop_projection

    def spy(state, **kwargs):
        seen.append(state)
        return original(state, **kwargs)

    module._read_loop_projection = spy
    try:
        _desugar_all(_write(tmp_path, FIXTURE))
    finally:
        module._read_loop_projection = original

    assert seen, "no LoopGuardedProjection read: the carrier moved"
    for projection in seen:
        kinds = {face.completion_kind for face in projection.completed_faces}
        assert kinds == {"BreakExit", "NormalExhaustion"}, kinds
        assert "BodyFallthrough" not in kinds
        faces = _loop_exit_faces(projection)
        assert faces is not None
        assert {face.side for face in faces.values()} == kinds
        assert {face.arity for face in faces.values()} == {2}
        assert {face.partition for face in faces.values()} == {
            ("sugar.exit_set.partition", ("loop.exit", projection.target_cid))
        }


def test_delete_uses_the_same_authenticated_loop_exit_family():
    """The delete verb stamps the same producer-owned faces as the read verb."""
    from dataclasses import dataclass

    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    @dataclass(frozen=True)
    class _Site:
        filename: str = "loop-delete-twin.py"
        line: int = 1
        col: int = 0

    class _BoundState(Sugar):
        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            raise AssertionError("delete_binding must not reduce a bound face")

    site = _Site()
    projection = _projection(
        [
            LoopGuardedCompletedFace("BreakExit", atomic("b", []), _BoundState(), 2),
            LoopGuardedCompletedFace(
                "NormalExhaustion",
                atomic("n", []),
                UnboundProjection("value", site),
                2,
            ),
        ]
    )

    exits = delete_binding(projection, name="value", site=site, ctx=None)

    assert {type(exit_).__name__ for exit_ in exits.exits} == {
        "Completed",
        "Halted",
    }
    assert {next(iter(exit_.faces)).side for exit_ in exits.exits} == {
        "BreakExit",
        "NormalExhaustion",
    }
    assert {next(iter(exit_.faces)).partition for exit_ in exits.exits} == {
        ("sugar.exit_set.partition", ("loop.exit", projection.target_cid))
    }


# --------------------------------------------------------------------------
# discriminators on the mint: one criterion each, all of them required
# --------------------------------------------------------------------------


def test_the_latch_is_never_a_member_of_the_exit_partition():
    """THE RULING'S OWN DISCRIMINATOR. `BodyFallthrough` is the loop-back edge.

    A projection that carries the latch alongside the exits is not a producer
    naming three exit routes; it is a projection that put the loop-back edge in
    the exit family. Refuse the mint outright rather than assert an exclusion
    between the latch and the routes that nobody established.
    """
    assert (
        _loop_exit_faces(
            _projection(
                [
                    _face("BreakExit", 3),
                    _face("BodyFallthrough", 3),
                    _face("NormalExhaustion", 3),
                ]
            )
        )
        is None
    )


def test_an_undeclared_family_size_mints_nothing():
    """DISCRIMINATING. A producer that never said how many routes it owns.

    Counting the faces that happened to arrive would read a DROPPED face as a
    smaller complete partition. No declaration, no family, gap stays loud.
    """
    assert (
        _loop_exit_faces(
            _projection([_face("BreakExit", None), _face("NormalExhaustion", None)])
        )
        is None
    )


def test_a_family_short_of_its_declared_size_mints_nothing():
    """DISCRIMINATING. Every face retained, or no admission.

    Two declared, one present: the absent route is an outcome nobody accounted
    for, and collapsing what is left would drop it.
    """
    assert _loop_exit_faces(_projection([_face("NormalExhaustion", 2)])) is None


def test_faces_disagreeing_on_the_declared_size_mint_nothing():
    """DISCRIMINATING. One occurrence declares ONE family size.

    Two different arities on one projection means the faces did not come from
    one statement of the split, so there is no single family to admit.
    """
    assert (
        _loop_exit_faces(
            _projection([_face("BreakExit", 2), _face("NormalExhaustion", 3)])
        )
        is None
    )


def test_an_unauthenticated_occurrence_mints_nothing():
    """DISCRIMINATING. The origin is the loop OCCURRENCE, not the loop's shape.

    Without a target CID there is nothing to key the family on, and keying on
    anything weaker -- the name read, the completion kinds, the arms' type --
    would let two unrelated loops share an exclusion.
    """
    assert (
        _loop_exit_faces(
            _projection(
                [_face("BreakExit", 2), _face("NormalExhaustion", 2)],
                target_cid=None,
            )
        )
        is None
    )


def test_indistinguishable_routes_mint_nothing():
    """DISCRIMINATING. Two members that cannot be told apart carry no exclusion."""
    assert (
        _loop_exit_faces(
            _projection([_face("NormalExhaustion", 2), _face("NormalExhaustion", 2)])
        )
        is None
    )


def test_two_loops_are_two_origins():
    """THE SAME-TYPE TRAP, at the carrier.

    Two loops in one function agree in completion kinds, in declared arity, and
    in the type of everything they carry. They share no origin, so their arms
    must not factor -- and this is the criterion the two measured rows are
    shaped to defeat.
    """
    other = "blake3-512:" + "cd" * 32
    left = _loop_exit_faces(
        _projection([_face("BreakExit", 2), _face("NormalExhaustion", 2)])
    )
    right = _loop_exit_faces(
        _projection(
            [_face("BreakExit", 2), _face("NormalExhaustion", 2)], target_cid=other
        )
    )

    assert left is not None and right is not None
    assert left["BreakExit"].partition != right["BreakExit"].partition

    from sugar_lift_py_tests.ir import atomic, make_var

    def guard(name):
        return atomic(name, [make_var("state")])

    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            (
                Completed(guard("p"), "v", frozenset({left["BreakExit"]})),
                Completed(guard("q"), "w", frozenset({right["NormalExhaustion"]})),
            )
        ).factor_completed()


# --------------------------------------------------------------------------
# the wire: the declaration is sealed testimony, not an annotation
# --------------------------------------------------------------------------


def _one_loop_graph(tmp_path) -> dict:
    """A REAL sealed loop wire graph, taken from the fixture as it lifts."""
    from sugar_source_tree import loop_recurrence as module

    captured: list[dict] = []
    original = module.project_loop_post_binding

    def spy(*, construction, **kwargs):
        captured.append(construction.wire_graph())
        return original(construction=construction, **kwargs)

    module.project_loop_post_binding = spy
    try:
        _desugar_all(_write(tmp_path, FIXTURE))
    finally:
        module.project_loop_post_binding = original

    assert captured, "no loop projection ran"
    return captured[0]


def _post_records(graph: dict) -> list[dict]:
    return [r for r in graph["records"] if r.get("kind") == "loop-post-binding"]


def test_the_real_wire_declares_two_exit_routes(tmp_path):
    """POSITIVE. The producer's own records say two, and name which two."""
    from sugar_lift_py_tests.loop_construction import decode_loop_construction_v1

    graph = _one_loop_graph(tmp_path)
    posts = _post_records(graph)
    assert posts
    assert {record["exitPartitionArity"] for record in posts} == {2}

    faces = {
        record["completedFaceCid"]: record["completionKind"]
        for record in graph["records"]
        if record.get("kind") == "loop-completed-face"
    }
    assert {faces[record["completedFaceCid"]] for record in posts} == {
        "BreakExit",
        "NormalExhaustion",
    }
    decode_loop_construction_v1(graph)  # the real decoder accepts it


def _with_producer_records(tmp_path, rewrite):
    """Run the fixture with one rewrite applied to preimages BEFORE they seal.

    Mutating a finished graph is not a way to reach these checks: every record
    carries its own CID and the root is sealed over the CIDs it binds, so a
    tampered graph fails on its seal long before any of the rules below get a
    turn. The reachable defect is a PRODUCER that mints the wrong record, so
    that is what these twins plant -- at the producer, where the result reseals
    into a graph that is internally valid and wrong only in the way under test.
    """
    from sugar_source_tree import live_loop_construction as producer

    original = producer._record
    seen: dict[str, str] = {}

    def rewriting_record(preimage, cid_field):
        if preimage.get("kind") == "loop-completed-face":
            record = original(preimage, cid_field)
            seen[preimage["completionKind"]] = record["completedFaceCid"]
            return record
        preimage = rewrite(preimage, seen)
        return original(preimage, cid_field)

    producer._record = rewriting_record
    try:
        _desugar_all(_write(tmp_path, FIXTURE))
    finally:
        producer._record = original


def test_a_post_binding_without_a_declared_arity_is_refused(tmp_path):
    """DISCRIMINATING, at the wire. No declaration is not a small family.

    A producer that mints the field but leaves it empty passes the record's
    field-set and seal checks, so this reaches the RULE rather than a generic
    malformed-record refusal -- which is the difference between a twin with
    teeth and a twin that passes for someone else's reason.
    """
    from sugar_lift_py_tests.loop_construction import LoopWireError

    def rewrite(preimage, _seen):
        if preimage.get("kind") == "loop-post-binding":
            return {**preimage, "exitPartitionArity": None}
        return preimage

    with pytest.raises(LoopWireError, match="must declare exitPartitionArity"):
        _with_producer_records(tmp_path, rewrite)


def test_a_post_binding_that_projects_the_latch_is_refused(tmp_path):
    """DISCRIMINATING, at the wire. The latch may not enter the exit family.

    THE MIS-STAMP THE RULING FORBIDS, planted at the layer that would have to
    carry it. A producer that projected `BodyFallthrough` would hand
    `read_binding` a family whose member is the loop-back edge, and the exits
    would be asserting an exclusion against an edge that is not an exit at all.
    """
    from sugar_lift_py_tests.loop_construction import LoopWireError

    def rewrite(preimage, seen):
        if preimage.get("kind") == "loop-post-binding" and "BodyFallthrough" in seen:
            return {**preimage, "completedFaceCid": seen["BodyFallthrough"]}
        return preimage

    with pytest.raises(LoopWireError, match="must not project BodyFallthrough"):
        _with_producer_records(tmp_path, rewrite)


def test_a_projection_short_of_the_declared_family_refuses(tmp_path):
    """DISCRIMINATING, at the projection. A family short of its size is LOUD.

    NOT FORGEABLE FROM OUTSIDE, AND THAT IS THE POINT. Deleting a post-binding
    record from a finished graph cannot reach this check: the record CIDs and
    the sealed root make a tampered graph fail the decoder first. The reachable
    way to get here is a PRODUCER BUG -- a loop that declares more exit routes
    than it mints post-binding records for -- so that is what this plants, by
    raising the declared arity to three inside the producer where it is sealed.

    Counting the faces that arrived would silently re-read the result as a
    complete two-face partition. The declaration is what turns it into a gap.
    """
    from sugar_source_tree import live_loop_construction as producer
    from sugar_source_tree.binding_state import BindingStateWireGap

    original = producer._record

    def overstating_record(preimage, cid_field):
        if preimage.get("kind") == "loop-post-binding":
            preimage = {**preimage, "exitPartitionArity": 3}
        return original(preimage, cid_field)

    producer._record = overstating_record
    try:
        with pytest.raises(BindingStateWireGap, match="short of its declared size"):
            _desugar_all(_write(tmp_path, FIXTURE))
    finally:
        producer._record = original


# --------------------------------------------------------------------------
# the #6333 guard: an admitted family may not start multiplying again
# --------------------------------------------------------------------------


def test_the_loop_family_stays_linear_as_factors_are_appended(tmp_path):
    """THE BOUND. A factored family that grows with appended factors is `m ** k`.

    The admission this file adds is only worth having if the collapsed face
    stays at one arm however many steps are sequenced after it.
    """
    from sugar_lift_py_tests.ir import atomic, make_var

    faces = _loop_exit_faces(
        _projection([_face("BreakExit", 2), _face("NormalExhaustion", 2)])
    )
    assert faces is not None

    def guard(name):
        return atomic(name, [make_var("state")])

    family = ExitSet(
        (
            Completed(guard("broke"), "a", frozenset({faces["BreakExit"]})),
            Completed(guard("exhausted"), "b", frozenset({faces["NormalExhaustion"]})),
        )
    ).factor_completed()

    series = []
    for step_count in (1, 2, 3, 4, 5, 6, 7, 8):
        exits = family
        for index in range(step_count):
            exits = exits.sequence(
                lambda value, _i=index: ExitSet.completed((value, _i))
            )
        series.append(len([e for e in exits.exits if isinstance(e, Completed)]))

    assert series == [1] * 8, (
        f"completed arms by appended factors {series}: the loop exit family is "
        "multiplying again (#6333)"
    )
