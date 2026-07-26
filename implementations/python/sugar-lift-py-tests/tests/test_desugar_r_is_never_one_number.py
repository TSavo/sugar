"""``R_desugar`` is a mixed number. Publishing the total is a 7.6x overstatement.

The rows behind ``R_desugar`` are two different things sharing one counter:

* a **typed refusal** — the reduction stopped and owes work;
* a **constructed effect** — the authenticated output of a reduction that
  *succeeded*. Accounted semantics, not a backlog.

On the earlier board 7,483 of 8,624 rows were the second kind. Quoted whole,
``R_desugar`` read as remaining work and was wrong by 7.6x.

The split is not a heuristic and not a name table: the occurrence key already
records which kind each row is, because a refusal is keyed by the desugar CALL
(``desugar-call:<where>``) while an effect is keyed by its own authenticated
occurrence coordinate. This test pins that the axis reports the split, that the
parts are disjoint and sum to the total, and — the discriminating face — that
the two kinds actually land in different buckets.
"""

from __future__ import annotations

from sugar_lift_py_tests.desugar_axis import DesugarAxis


def test_the_split_is_disjoint_and_conserves_the_total() -> None:
    axis = DesugarAxis()
    axis._tally("SomeSugar", "desugar-call:pkg/m.py:10:4")
    axis._tally("SomeSugar", "desugar-call:pkg/m.py:20:4")
    axis._tally("SubscriptStoreRuntimeEffect", "pkg/m.py:11:8#store")
    axis._tally("RaiseEffect", "pkg/m.py:12:8#raise")
    axis._tally("RaiseEffect", "pkg/m.py:13:8#raise")

    row = axis.row()
    assert row["R_desugar"] == 5
    assert row["R_desugar_owed_work"] == 2
    assert row["R_desugar_accounted_semantics"] == 3
    # Disjoint, and conserving: the parts are the whole, with nothing dropped
    # into an unnamed remainder.
    assert row["R_desugar_owed_work"] + row["R_desugar_accounted_semantics"] == (
        row["R_desugar"]
    )
    assert sum(row["desugarCategories"].values()) == row["R_desugar"]


def test_the_two_kinds_do_not_land_in_the_same_bucket() -> None:
    """Discriminating face: if both landed together the split proves nothing."""
    refusals = DesugarAxis()
    refusals._tally("SomeSugar", "desugar-call:pkg/m.py:1:0")
    assert refusals.row()["desugarCategories"] == {"typed-refusal": 1}

    effects = DesugarAxis()
    effects._tally("RaiseEffect", "pkg/m.py:1:0#raise")
    assert effects.row()["desugarCategories"] == {"constructed-effect": 1}


def test_owner_is_kept_within_its_category() -> None:
    """One owner can produce both kinds; the ranking must not merge them.

    Ranking by owner alone would put a refusal and its own successful effects
    in one row and make the owner look like more work than it is.
    """
    axis = DesugarAxis()
    axis._tally("YieldSuspensionSugar", "desugar-call:pkg/m.py:1:0")
    axis._tally("YieldSuspensionSugar", "pkg/m.py:2:0#effect")

    by_owner = axis.row()["desugarByCategoryOwner"]
    assert by_owner == {
        "typed-refusal/YieldSuspensionSugar": 1,
        "constructed-effect/YieldSuspensionSugar": 1,
    }
    # And the flat family count still sees one owner with two rows, which is
    # exactly the number that must never be published as owed work.
    assert axis.row()["desugarFamilies"] == {"YieldSuspensionSugar": 2}


def test_merge_carries_the_split() -> None:
    """A per-file axis folded into the run total must not lose its categories."""
    whole = DesugarAxis()
    part = DesugarAxis()
    part._tally("SomeSugar", "desugar-call:pkg/m.py:1:0")
    part._tally("RaiseEffect", "pkg/m.py:2:0#raise")
    whole.merge(part)

    row = whole.row()
    assert row["R_desugar_owed_work"] == 1
    assert row["R_desugar_accounted_semantics"] == 1
    assert row["R_desugar"] == 2
