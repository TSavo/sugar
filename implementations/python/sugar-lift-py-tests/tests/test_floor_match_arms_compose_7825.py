"""#7825 / #7757: the floor and match arm lists compose or join (after #8041).

The hand-assembled arm lists in ``floor/*`` and ``sugar/match_sugar.py`` now
compose through ``ExitSet.sequence``, join through ``ExitSet.union``, or build
one fresh arm with ``ExitSet.completed`` / ``ExitSet.halted``. Each assembly
that dropped what an arm carried has a test here that it now survives, and
``ExitSet.with_partition_face`` (which read an ``exit_.partition`` no arm has)
stamps the face ``partition`` mints.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import MutableGlobalValue, StringValue, TermValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.lift_rpc import _open_at_seat
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    _faces_exclusive,
    complement_guard,
    partition,
)
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.match_sugar import (
    MatchCaseSpec,
    MatchSugar,
    ValuePatternSpec,
)
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.nodes import Name, Subscript


def _raised(occurrence: str) -> RaiseEffect:
    return RaiseEffect.for_builtin("ValueError", occurrence=occurrence)


# -- ExitSet.with_partition_face ----------------------------------------------


def test_with_partition_face_stamps_the_minted_face_and_keeps_every_arm() -> None:
    # It read ``exit_.partition``, which ``Completed`` does not have, so any
    # call over a completed arm raised AttributeError.
    prior, _other = partition(("test:prior-split", 7825))
    guard = atomic("test:stamp:7825", [])
    arms = ExitSet(
        (
            Completed(guard, TermValue(1), frozenset({prior}), ("debt:done",)),
            Halted(
                complement_guard(guard),
                _raised("test:stamp-raise:7825"),
                owed=("debt:halt",),
            ),
        )
    )
    then_face, else_face = partition("test:stamp-split:7825")

    done, halt = arms.with_partition_face("test:stamp-split:7825", 0).exits
    assert isinstance(done, Completed)
    assert done.guard == guard
    assert done.value == TermValue(1)
    assert done.faces == frozenset({prior, then_face})
    assert done.owed == ("debt:done",)
    # A halted arm stands as it was.
    assert isinstance(halt, Halted)
    assert halt == arms.exits[1]
    assert halt.faces == frozenset()
    assert halt.owed == ("debt:halt",)

    (other_done, _halt) = arms.with_partition_face("test:stamp-split:7825", 1).exits
    assert other_done.faces == frozenset({prior, else_face})
    # The two stamps are the two sides of one split.
    assert _faces_exclusive(done.faces, other_done.faces)


# -- MutableGlobalValue.subscript ---------------------------------------------


def _lookup_site(tmp_path):
    filename = "mutable_global_arms_7825.py"
    (tmp_path / filename).write_text("OPTIONS = {}\nvalue = OPTIONS[key]\n")
    tree = _open_at_seat(tmp_path / filename, root=tmp_path)
    binding = next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Name) and node.fragment.text == "OPTIONS"
    )
    lookup = next(node for node in tree.nodes() if isinstance(node, Subscript))
    return binding, lookup.fragment


def test_a_mutable_global_lookup_splits_beneath_every_coordinate_arm(
    tmp_path, monkeypatch
) -> None:
    # The lookup read the coordinate through ``completed_value()``: a
    # coordinate of more than one arm completed with ``None``, its halt was
    # dropped, and the KeyError arm owed nothing of what the coordinate owed.
    monkeypatch.chdir(tmp_path)
    binding, site = _lookup_site(tmp_path)
    completes = atomic("test:coordinate-completes:7825", [])
    coordinate = ExitSet(
        (
            Completed(completes, TermValue(1), owed=("debt:coordinate",)),
            Halted(
                complement_guard(completes),
                _raised("test:coordinate-raise:7825"),
                owed=("debt:coordinate",),
            ),
        )
    )
    monkeypatch.setattr(
        MutableGlobalValue,
        "py_subscript_coordinate",
        lambda self, index, site: coordinate,
    )
    value = MutableGlobalValue("OPTIONS", "dict", binding.source_cid, binding.seal())

    exits = value.subscript(StringValue("display.max_rows"), site).exits

    completed = [arm for arm in exits if isinstance(arm, Completed)]
    assert [arm.value for arm in completed] == [TermValue(1)]
    assert completed[0].owed == ("debt:coordinate",)
    halts = {
        arm.effect.exception_name: arm for arm in exits if isinstance(arm, Halted)
    }
    assert set(halts) == {"KeyError", "ValueError"}
    assert halts["KeyError"].owed == ("debt:coordinate",)
    assert halts["ValueError"].guard == complement_guard(completes)
    # The lookup's own split still marks its two faces.
    (key_error_face,) = halts["KeyError"].faces
    (value_face,) = completed[0].faces
    assert key_error_face.partition == value_face.partition
    assert key_error_face.side != value_face.side


# -- MatchSugar ---------------------------------------------------------------


@dataclass(frozen=True)
class _Site:
    filename: str = "match_arms_7825.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _int(n: int) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=_Site(col=n))


def _ret(n: int) -> ReturnSugar:
    return ReturnSugar(_int(n), site=_Site(line=n))


@dataclass(frozen=True)
class _Truth:
    """A completed value whose truth is the symbolic ``formula``."""

    formula: object

    def truth(self, site):
        del site
        return ExitSet.completed(self)


@dataclass(frozen=True)
class _Outcome(Sugar):
    """A sugar that desugars to a fixed outcome."""

    outcome: object
    site: object = SITE
    # A canned statement binds nothing before its halts: the block's prefix
    # is their record.
    halts_at_statement_head = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return self.outcome


@dataclass(frozen=True)
class _Subject:
    """A subject whose ``__eq__`` answers the symbolic ``_EQ``."""

    def equals(self, other, site, ctx):
        del other, site, ctx
        return ExitSet.completed(_Truth(_EQ))


_EQ = atomic("test:match-subject-eq:7825", [])


def _selected(outcome: ExitSet) -> list:
    """The arms that returned (the fall-through arm continues)."""
    return [
        arm
        for arm in outcome.exits
        if isinstance(arm, Completed) and not arm.value.can_fall_through
    ]


def test_a_match_body_runs_beneath_its_guard_face() -> None:
    # The body was sequenced after a debt-only arm for the guard face, so
    # every body arm dropped the guard face's partition testimony.
    side, _other = partition(("test:guard-face", 7825))
    guard = atomic("test:guard-face:7825", [])
    guard_out = ExitSet(
        (
            Completed(
                guard,
                _Truth(atomic("test:guard-truth:7825", [])),
                frozenset({side}),
                ("debt:guard",),
            ),
        )
    )
    outcome = MatchSugar(
        subject=_int(5),
        cases=(
            MatchCaseSpec(
                alternatives=(), body=(_ret(10),), guard=_Outcome(guard_out)
            ),
        ),
        site=SITE,
    ).desugar(ReduceContext.root(owner="test_match_guard_face_7825"))

    (selected,) = _selected(outcome)
    assert side in selected.faces
    assert selected.owed == ("debt:guard",)


def test_a_structural_case_body_runs_beneath_its_matched_face() -> None:
    # The body was restricted by the matched face's guard alone, so every
    # body arm dropped the pattern's partition testimony.
    matched, _missed = partition(("MatchPattern", SITE, _EQ))
    outcome = MatchSugar(
        subject=_Outcome(ExitSet.completed(_Subject())),
        cases=(
            MatchCaseSpec(
                alternatives=(),
                body=(_ret(10),),
                pattern=ValuePatternSpec(_int(1)),
            ),
        ),
        site=SITE,
    ).desugar(ReduceContext.root(owner="test_match_structural_face_7825"))

    (selected,) = _selected(outcome)
    assert selected.guard == _EQ
    assert matched in selected.faces
