"""The desugar axis (#6243/#6244): four disjoint quantities, exact cardinality.

Every twin here asserts an EXACT count. ``>= 1`` passes with extra incorrect
rows and with a misclassified owner — which is exactly how a second axis starts
reporting a useful-looking number whose denominator is not honest.

The four quantities the door produces, and which twin separates them:

    R_desugar                  typed refusals + typed red effects   (1, 2, 3, 5, 8)
    R_construction             tree construction totality           (4)
    desugarConstructionPanics  construction law during desugar      (6)
    desugarDefects             ordinary + audit/instrument defects  (7, 9)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSugar:
    """A constructed sugar whose desugar outcome (or panic) is dictated."""

    def __init__(self, *, outcome=None, raises=None) -> None:
        self._outcome = outcome
        self._raises = raises

    def desugar(self, ctx=None):
        del ctx
        if self._raises is not None:
            raise self._raises
        return self._outcome


def _raise_effect(occurrence: str):
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    return RaiseEffect(exception_name="ValueError", occurrence=occurrence)


def _incomplete(occurrence: str):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(_raise_effect(occurrence))


def _axis():
    from sugar_lift_py_tests.desugar_axis import DesugarAxis

    return DesugarAxis()


# -- 1. one YieldFrom refusal -> EXACTLY one desugar row ---------------------


def test_twin_1_yield_from_refusal_is_exactly_one_desugar_row(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "gen.py"
    path.write_text("def f(xs):\n    yield from xs\n", encoding="utf-8")
    row = module._measure_file(path, relative="gen.py", workspace_root=tmp_path)
    assert row["category"] == "completed"
    assert row["functionsClean"] == 1
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"YieldFromSugar.desugar": 1}


# -- 2. two same-class effects on DIFFERENT sites -> two rows ----------------


def test_twin_2_two_effect_sites_are_two_rows() -> None:
    axis = _axis()
    outcome = (_incomplete("gen.py:2:4"), _incomplete("gen.py:7:4"))
    axis.measure(_FakeSugar(outcome=outcome), where="gen.py:1:0")
    row = axis.row()
    # The defect this bites: keying by the enclosing function's DEFINITION line
    # collapses both raises into one row, because both live in one function.
    assert row["R_desugar"] == 2
    assert row["desugarFamilies"] == {"RaiseEffect": 2}


# -- 3. the SAME occurrence reached twice -> one row -------------------------


def test_twin_3_same_occurrence_twice_is_one_row() -> None:
    axis = _axis()
    shared = _incomplete("gen.py:2:4")
    # Once as a shared object (lawful DAG re-entry), once as an equal-coordinate
    # twin reached down another edge.
    outcome = (shared, shared, _incomplete("gen.py:2:4"))
    axis.measure(_FakeSugar(outcome=outcome), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"RaiseEffect": 1}


# -- 4. a construction gap changes ONLY R_construction ----------------------


def test_twin_4_construction_gap_moves_only_the_construction_axis(
    tmp_path: Path,
) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "coro.py"
    path.write_text("async def h(x):\n    return x\n", encoding="utf-8")
    row = module._measure_file(path, relative="coro.py", workspace_root=tmp_path)
    assert row["functionsClean"] == 0
    # ONE gap occurrence, tallied once (catch + reporter is not two rows).
    assert row["families"] == {"SugarNotWritten": 1}
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarConstructionPanics"] == []
    assert row["desugarDefects"] == []


# -- 5. a typed desugar refusal changes ONLY R_desugar ----------------------


def test_twin_5_typed_refusal_moves_only_the_desugar_axis(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "gen.py"
    path.write_text("def f(xs):\n    yield from xs\n", encoding="utf-8")
    row = module._measure_file(path, relative="gen.py", workspace_root=tmp_path)
    assert row["families"] == {}
    assert row["R_desugar"] == 1
    assert row["desugarConstructionPanics"] == []
    assert row["desugarDefects"] == []


# -- 6. ConstructionPanic -> ONLY desugarConstructionPanics, and RED --------


def test_twin_6_construction_panic_is_its_own_collection_and_red() -> None:
    axis = _axis()
    panic = ConstructionPanic(
        ConstructionGap(
            owner="MissingConstructor",
            blame="gen.py:2:4",
            observed="OpaqueValue",
            requested="constructed value",
            fix="implement the constructor",
        )
    )
    # A BaseException: neither `except SugarNotWritten` nor `except Exception`
    # sees it. Unhandled it escapes the per-function loop and can abort a whole
    # census run with no row at all.
    axis.measure(_FakeSugar(raises=panic), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarDefects"] == []
    assert len(row["desugarConstructionPanics"]) == 1
    assert row["desugarConstructionPanics"][0]["owner"] == "MissingConstructor"
    assert axis.red is True
    # ...and measurement CONTINUES: the next function is still measured.
    axis.measure(_FakeSugar(outcome=_incomplete("gen.py:9:4")), where="gen.py:8:0")
    assert axis.row()["R_desugar"] == 1


# -- 7. an ordinary Exception -> ONLY desugarDefects, and RED ---------------


def test_twin_7_ordinary_exception_is_a_defect_not_semantic_r() -> None:
    axis = _axis()
    axis.measure(_FakeSugar(raises=KeyError("boom")), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarConstructionPanics"] == []
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["kind"] == "desugar-exception"
    assert row["desugarDefects"][0]["detail"].startswith("KeyError")
    assert axis.red is True


# -- 8. depth GREATER than 24 is still fully measured -----------------------


def test_twin_8_no_semantic_depth_cap() -> None:
    from sugar_lift_py_tests.outcome import Complete

    axis = _axis()
    outcome: object = _incomplete("deep.py:40:8")
    for _ in range(40):  # far past the deleted `if depth > 24: return`
        outcome = Complete(outcome)  # type: ignore[arg-type]
    axis.measure(_FakeSugar(outcome=outcome), where="deep.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 1
    assert row["desugarFamilies"] == {"RaiseEffect": 1}
    assert row["desugarDefects"] == []


# -- 9. cyclic / unsupported outcome traversal -> a LOUD audit defect -------


def test_twin_9_cycle_is_a_named_audit_defect() -> None:
    axis = _axis()
    cycle: list = [_incomplete("gen.py:2:4")]
    cycle.append(cycle)
    axis.measure(_FakeSugar(outcome=cycle), where="gen.py:1:0")
    row = axis.row()
    # The reachable effect is still measured; the cycle is NAMED, never an
    # empty return.
    assert row["R_desugar"] == 1
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["kind"] == "audit-defect"
    assert row["desugarDefects"][0]["detail"] == "outcome-cycle:list"
    assert axis.red is True


def test_twin_9_unsupported_outcome_envelope_is_a_named_audit_defect() -> None:
    unsupported = type("UnwalkableEnvelope", (), {})
    # In the lift's own domain, so the walk is obliged to descend it — and it
    # is neither a dataclass nor a container.
    unsupported.__module__ = "sugar_lift_py_tests.fake_envelope"
    axis = _axis()
    axis.measure(_FakeSugar(outcome=unsupported()), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert len(row["desugarDefects"]) == 1
    assert (
        row["desugarDefects"][0]["detail"]
        == "unsupported-outcome-envelope:UnwalkableEnvelope"
    )
    assert axis.red is True


# -- the instrument gap: an effect that states no occurrence -----------------


def test_effect_without_occurrence_is_an_instrument_gap_not_a_fabricated_key() -> None:
    """No authenticated coordinate => NO row and a named instrument gap.

    The forbidden alternative is substituting the enclosing function's line,
    which silently collapses distinct effects and inflates nothing visibly.
    """
    from sugar_lift_py_tests.effect.source_oracle_effect import SourceOracleEffect
    from sugar_lift_py_tests.outcome import Incomplete

    axis = _axis()
    effect = SourceOracleEffect(reason="source absent")
    axis.measure(
        _FakeSugar(outcome=(Incomplete(effect), Incomplete(effect))),
        where="gen.py:1:0",
    )
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert len(row["desugarDefects"]) == 2
    assert {d["kind"] for d in row["desugarDefects"]} == {"instrument-gap"}
    assert {d["detail"] for d in row["desugarDefects"]} == {
        "no-occurrence-coordinate:SourceOracleEffect"
    }
    assert axis.red is True


# -- 10. a row carries the classification its exception already holds --------
#
# The pandas board reported thirteen `ExitSetFactoringGap` occurrences as
# undifferentiated rows, while the exception itself carried the two refusing
# arms and a classifier that splits them into closable work and correct output.
# These twins own the READING of that testimony and assert EXACT cardinality;
# twin 11 owns which axis the row lands on.


def _factoring_gap(*, stamped: bool):
    """One `ExitSetFactoringGap` carrying two arms, silent or testifying."""
    from sugar_lift_py_tests.ir import atomic, make_var, not_
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSetFactoringGap,
        partition,
    )

    guard = atomic("g", [make_var("state")])
    if stamped:
        # Both arms testify to the SAME side of one producer's split — which is
        # why the split does not separate them, and why wiring a producer
        # cannot close this occurrence.
        face, _other_side = partition("twin-producer")
        left = Completed(guard, "A", frozenset({face}))
        right = Completed(not_(guard), "B", frozenset({face}))
    else:
        left = Completed(guard, "A", frozenset())
        right = Completed(not_(guard), "B", frozenset())
    return ExitSetFactoringGap("arms are not provably exclusive", left, right)


def test_twin_10_factoring_gap_carries_its_classification() -> None:
    """An UNSTAMPED, unmerged pair is OWED WORK, so its row is a defect — and it
    still carries the verdict that says so. This twin owns the READING; twin 12
    owns the membership rule that keeps this population red."""
    axis = _axis()
    axis.measure(_FakeSugar(raises=_factoring_gap(stamped=False)), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar"] == 0
    assert row["desugarFamilies"] == {}
    assert row["desugarConstructionPanics"] == []
    assert len(row["desugarDefects"]) == 1
    defect = row["desugarDefects"][0]
    assert defect["kind"] == "desugar-exception"
    assert defect["detail"].startswith("ExitSetFactoringGap")
    assert defect["classification"]["kind"] == "unstamped"
    assert defect["classification"]["isRemainingWork"] is True


def test_twin_10_discriminator_stamped_arms_are_not_reported_as_owed_work() -> None:
    """The same row shape, the other verdict.

    A classifier that answered one constant would satisfy the positive twin
    above. Two producers that already testified and still do not separate are
    NOT closable by wiring a producer, and the row must say so.
    """
    axis = _axis()
    axis.measure(_FakeSugar(raises=_factoring_gap(stamped=True)), where="gen.py:1:0")
    gaps = axis.row()["desugarDesignedGaps"]
    assert len(gaps) == 1
    assert gaps[0]["classification"]["kind"] == "stamped-not-separating"
    assert gaps[0]["classification"]["isRemainingWork"] is False
    assert axis.red is False


def test_twin_10_discriminator_an_exception_with_no_testimony_gets_no_key() -> None:
    """No placeholder. An ordinary exception carries no classification, and the
    row must OMIT the key rather than carry an "unknown" a reader could read as
    a verdict."""
    axis = _axis()
    axis.measure(_FakeSugar(raises=KeyError("boom")), where="gen.py:1:0")
    defects = axis.row()["desugarDefects"]
    assert len(defects) == 1
    assert "classification" not in defects[0]

    # ...and neither does a factoring gap that carries no arms at all, on its
    # own axis. An absent verdict is an ABSENT KEY, never an "unknown".
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    bare = _axis()
    bare.measure(_FakeSugar(raises=ExitSetFactoringGap("bare")), where="gen.py:2:0")
    bare_defects = bare.row()["desugarDefects"]
    assert len(bare_defects) == 1
    assert "classification" not in bare_defects[0]


def test_twin_10_discriminator_a_merged_arm_is_not_reported_as_owed_work() -> None:
    """Silent arms are not automatically owed work.

    An equal-destination merge puts a disjunction at conjunct level, and #6336's
    composition rule intersects faces on such a merge — so minting the producer's
    face would only see it intersected away again (#6361 measured exactly that).
    An `UNSTAMPED` row with a merged arm must therefore read `isRemainingWork:
    False`, and this twin is the one that fails when the merged-arm condition is
    dropped from `is_remaining_work`.
    """
    from sugar_lift_py_tests.ir import atomic, make_var, not_, or_
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSetFactoringGap

    guard = atomic("g", [make_var("state")])
    merged = or_([guard, atomic("h", [make_var("state")])])
    gap = ExitSetFactoringGap(
        "arms are not provably exclusive",
        Completed(merged, "A", frozenset()),
        Completed(not_(guard), "B", frozenset()),
    )
    axis = _axis()
    axis.measure(_FakeSugar(raises=gap), where="gen.py:1:0")
    gaps = axis.row()["desugarDesignedGaps"]
    assert len(gaps) == 1
    assert gaps[0]["classification"]["kind"] == "unstamped"
    assert gaps[0]["classification"]["mergedArm"] is True
    assert gaps[0]["classification"]["isRemainingWork"] is False


# -- 11. a DECLARED designed gap is correct output, counted in its own bucket --
#
# `ExitSetFactoringGap` is a `ValueError`, so it landed in `desugarDefects` —
# twelve rows of the pandas board, every one classifying `isRemainingWork:
# False`, which is `factor_completed` doing exactly its job. Counting correct
# output as a defect is the 7.6x disease at smaller scale.
#
# The door is BY DECLARED TYPE. The lying face below is the one that matters:
# an undeclared `ValueError` must still be a defect, because a door shaped like
# "a ValueError out of this call" would swallow every genuine `ValueError` bug
# under desugar — a cure worse than the disease.


def test_twin_11_a_declared_designed_gap_is_counted_not_a_defect() -> None:
    axis = _axis()
    # `stamped=True` is the CORRECT-OUTPUT population. The other one is work and
    # twin 12 holds it red; using it here would have made this twin assert that
    # a closable producer-omission is a finished result.
    axis.measure(_FakeSugar(raises=_factoring_gap(stamped=True)), where="gen.py:1:0")
    row = axis.row()
    # Off the defect axis, and NOT onto any other measured quantity.
    assert row["desugarDefects"] == []
    assert row["R_desugar"] == 0
    assert row["desugarConstructionPanics"] == []
    # Counted, named, and carrying the verdict it already held.
    assert row["R_desugar_designed_gaps"] == 1
    assert row["desugarDesignedGapOwners"] == {"ExitSetFactoringGap": 1}
    assert len(row["desugarDesignedGaps"]) == 1
    gap = row["desugarDesignedGaps"][0]
    assert gap["owner"] == "ExitSetFactoringGap"
    assert gap["where"] == "gen.py:1:0"
    assert gap["classification"]["kind"] == "stamped-not-separating"
    assert gap["classification"]["isRemainingWork"] is False
    # Correct output does not hold the instrument red.
    assert axis.red is False


def test_twin_11_lying_an_undeclared_ValueError_is_still_a_defect() -> None:
    """THE discriminator. `ExitSetFactoringGap` IS a `ValueError`, so a door
    keyed on the exception's base class — or on "whatever came out of this
    call" — would silently absorb every genuine `ValueError` bug raised under
    desugar. Membership is the declared type and nothing else."""
    axis = _axis()
    axis.measure(_FakeSugar(raises=ValueError("a real bug")), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar_designed_gaps"] == 0
    assert row["desugarDesignedGaps"] == []
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["detail"].startswith("ValueError")
    assert axis.red is True


def test_twin_11_lying_a_subclass_is_a_different_mechanism() -> None:
    """Exact type identity, not `isinstance`. A subclass of a declared gap is a
    mechanism nobody declared; admitting it would let a new refusal join the
    correct-output bucket without anyone deciding that it should."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    class UndeclaredSubclassGap(ExitSetFactoringGap):
        pass

    axis = _axis()
    axis.measure(
        _FakeSugar(raises=UndeclaredSubclassGap("not declared")), where="gen.py:1:0"
    )
    row = axis.row()
    assert row["R_desugar_designed_gaps"] == 0
    assert len(row["desugarDefects"]) == 1
    assert axis.red is True


def test_twin_11_designed_gaps_survive_merge_and_stay_disjoint() -> None:
    """Per-file axes are merged into the run's row; a bucket that does not
    merge reports zero for every file but the last. Exact cardinality on both
    sides, and the four quantities stay disjoint across the merge."""
    left = _axis()
    left.measure(_FakeSugar(raises=_factoring_gap(stamped=True)), where="a.py:1:0")
    right = _axis()
    right.measure(_FakeSugar(raises=_factoring_gap(stamped=True)), where="b.py:1:0")
    right.measure(_FakeSugar(raises=KeyError("boom")), where="b.py:9:0")

    left.merge(right)
    row = left.row()
    assert row["R_desugar_designed_gaps"] == 2
    assert row["desugarDesignedGapOwners"] == {"ExitSetFactoringGap": 2}
    assert [gap["where"] for gap in row["desugarDesignedGaps"]] == [
        "a.py:1:0",
        "b.py:1:0",
    ]
    # The real defect is untouched by any of it, and still red.
    assert len(row["desugarDefects"]) == 1
    assert left.red is True


# -- 12. TYPE IS NECESSARY, NOT SUFFICIENT ----------------------------------
#
# A declared type says which MECHANISM spoke, never that this occurrence was the
# mechanism working. `ExitSetFactoringGap` has two populations and its own
# classifier separates them: `isRemainingWork: False` is the gate doing its job,
# `isRemainingWork: True` is UNSTAMPED-and-not-merged — a producer that owns a
# split and has not testified, which is closable work and exactly what #6375
# closed at `selectn.py:224`.
#
# Gating on type alone files the second kind into a bucket that is never red and
# never summed: a closable producer-omission published as a finished result and
# silenced. That is the worse direction — counting correct output as a defect is
# loud and self-correcting; counting work as correct output is neither. It is
# latent only because every occurrence on today's board classifies `False`,
# which is a fact about one measurement and not a property of the type.


def test_twin_12_a_declared_gap_that_is_REMAINING_WORK_stays_a_red_defect() -> None:
    """The arm that cannot be bought back later."""
    gap = _factoring_gap(stamped=False)
    # Precondition asserted, not assumed: if the classifier ever stops calling
    # this shape owed work, this test must fail loudly rather than pass because
    # its fixture drifted into the other population.
    assert gap.classification().is_remaining_work is True

    axis = _axis()
    axis.measure(_FakeSugar(raises=gap), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar_designed_gaps"] == 0
    assert row["desugarDesignedGaps"] == []
    assert len(row["desugarDefects"]) == 1
    assert row["desugarDefects"][0]["classification"]["isRemainingWork"] is True
    assert axis.red is True


def test_twin_12_the_mirror_correct_output_still_reaches_the_quiet_bucket() -> None:
    """The other face. A gate that refused everything would satisfy the twin
    above; correct output must still be re-attributed and must not hold the
    run red."""
    gap = _factoring_gap(stamped=True)
    assert gap.classification().is_remaining_work is False

    axis = _axis()
    axis.measure(_FakeSugar(raises=gap), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar_designed_gaps"] == 1
    assert row["desugarDefects"] == []
    assert axis.red is False


def test_twin_12_no_verdict_is_not_a_verdict_of_designed() -> None:
    """An unclassifiable occurrence must not DEFAULT into the quiet bucket.

    `classification()` answers `None` when the refusal carries no arms. Silence
    from the classifier is not a finding of correct output, so the row stays a
    defect and stays red — the same rule as the absent-key discipline in twin 10,
    applied to membership instead of to reporting.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    bare = ExitSetFactoringGap("carries no arms")
    assert bare.classification() is None

    axis = _axis()
    axis.measure(_FakeSugar(raises=bare), where="gen.py:1:0")
    row = axis.row()
    assert row["R_desugar_designed_gaps"] == 0
    assert len(row["desugarDefects"]) == 1
    assert axis.red is True
