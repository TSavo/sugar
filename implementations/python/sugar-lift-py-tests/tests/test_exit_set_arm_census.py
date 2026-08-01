"""Teeth for the #6309 halted-face arm census instrument.

The instrument lives in ``scripts/exit_set_arm_census.py`` and only
method-patches ``ExitSet``; no production file moves, so the source stamp does
not move either.

Two things are under test here, and they are different:

1. **The instrument reconciles.** Every row's predicted arm counts, rebuilt
   from the recorded input cardinalities alone, must equal what the site
   actually appended. A non-reconciling row is an instrument bug, never a
   finding -- so this is the tooth that has to hold before any number the
   census prints is worth reading.

2. **The halted face grows as a product at three of the four sites, and is
   flat at the fourth.** ``sequence`` is the control: its halted bypass means
   halted arms out stay equal to halted incomings no matter how wide the other
   operand gets. If the control ever showed growth, the law would be measuring
   the harness rather than the algebra.
"""

import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundaryDisposition,
    EffectMatcher,
    NeverSuppresses,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from exit_set_arm_census import SITES, arm_census, totals  # noqa: E402

_WIDTHS = (1, 2, 4, 8)


def _guard(name: str):
    return atomic(name, [make_var("state")])


def _effect(name: str = "ValueError"):
    return RaiseEffect.for_builtin(name, occurrence='implementations/python/sugar-lift-py-tests/tests/test_exit_set_arm_census.py:49:0')


def _value():
    """A completed value ``and_exit_truthiness`` can read a truth face from.

    ``exit_set.py:513`` takes the literal fast path for a ``TermValue`` holding
    a ``bool``; anything else is handed to ``predicate_formula``, which needs a
    floor value. A bare string would make the fixture, not the algebra, decide
    whether the site is reachable.
    """
    return TermValue(True)


def _mixed(width: int, prefix: str) -> ExitSet:
    """``width`` completed arms and ``width`` halted arms, distinctly guarded."""
    exits = []
    for index in range(width):
        exits.append(Completed(_guard(f"{prefix}_c{index}"), _value()))
        exits.append(
            Halted(_guard(f"{prefix}_h{index}"), _effect(), f"{prefix}_s{index}")
        )
    return ExitSet(tuple(exits))


def _completed_only(width: int, prefix: str) -> ExitSet:
    return ExitSet(
        tuple(
            Completed(_guard(f"{prefix}_c{index}"), _value()) for index in range(width)
        )
    )


def _rows_for(rows, site):
    return [row for row in rows if row.site == site]


def _assert_all_reconcile(rows):
    broken = [row for row in rows if not row.reconciles]
    assert not broken, "\n".join(
        f"{row.site}: {row.reconcile_detail} :: {row}" for row in broken
    )
    assert rows, "census collected no rows; the instrument never fired"


# --------------------------------------------------------------------------
# 1. the instrument reconciles
# --------------------------------------------------------------------------


@pytest.mark.parametrize("width", _WIDTHS)
def test_every_row_reconciles_at_and_exit_truthiness(width: int) -> None:
    body = _mixed(width, "body")
    exit_es = _mixed(width, "exit")

    with arm_census() as rows:
        body.and_exit_truthiness(exit_es, site=None)

    _assert_all_reconcile(_rows_for(rows, "and_exit_truthiness"))


@pytest.mark.parametrize("width", _WIDTHS)
def test_every_row_reconciles_at_and_finally(width: int) -> None:
    body = _mixed(width, "body")
    cleanup = _mixed(width, "clean")

    with arm_census() as rows:
        body.and_finally(lambda: cleanup)

    _assert_all_reconcile(_rows_for(rows, "and_finally"))


@pytest.mark.parametrize("width", _WIDTHS)
def test_every_row_reconciles_at_and_exit(width: int) -> None:
    body = _mixed(width, "body")
    exit_es = _mixed(width, "exit")

    with arm_census() as rows:
        body.and_exit(exit_es, disposition=NeverSuppresses())

    _assert_all_reconcile(_rows_for(rows, "and_exit"))


@pytest.mark.parametrize("width", _WIDTHS)
def test_every_row_reconciles_at_sequence(width: int) -> None:
    body = _mixed(width, "body")
    tail = _mixed(2, "tail")

    with arm_census() as rows:
        body.sequence(lambda _value: tail)

    _assert_all_reconcile(_rows_for(rows, "sequence"))


def test_conservation_holds_with_no_remainder_bucket() -> None:
    """completed_out + halted_from_exit + halted_from_incoming == pre_len."""
    body = _mixed(3, "body")
    other = _mixed(3, "other")

    with arm_census() as rows:
        body.and_exit_truthiness(other, site=None)
        body.and_finally(lambda: other)
        body.and_exit(other, disposition=NeverSuppresses())

    _assert_all_reconcile(rows)
    for row in rows:
        assert (
            row.completed_out + row.halted_from_exit + row.halted_from_incoming
            == row.pre_len
        ), f"{row.site} leaves a remainder: {row}"


def test_reconcile_check_can_actually_fail() -> None:
    """Negative control: a check nothing can fail is not a check.

    Every ``reconciles`` assertion above is only worth reading if a wrong
    prediction is caught. Perturb each predicted column on a known-good row and
    require the row to go red.
    """
    body = _mixed(2, "body")
    other = _mixed(2, "other")

    with arm_census() as rows:
        body.and_exit_truthiness(other, site=None)

    (row,) = _rows_for(rows, "and_exit_truthiness")
    assert row.reconciles, row.reconcile_detail

    for column in (
        "halted_from_exit",
        "halted_from_incoming",
        "predicted_completed_out",
        "predicted_pre_len",
    ):
        good = getattr(row, column)
        setattr(row, column, good + 1)
        row.check()
        assert not row.reconciles, f"perturbing {column} was not caught"
        setattr(row, column, good)

    row.check()
    assert row.reconciles, row.reconcile_detail


def test_verdict_probe_construction_panic_is_a_named_non_reconciling_row(
    monkeypatch,
) -> None:
    """LYING TWIN: the audit may hold the panic only as an explicit red row."""
    import sugar_lift_py_tests.outcome.exit_disposition as disposition_module

    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    real_effect = disposition_module.exit_disposition_effect
    calls = 0

    def panic_on_audit_probe(disposition, incoming):
        nonlocal calls
        calls += 1
        if calls == 2:
            construction_panic_gap(
                owner="exit-arm-census.verdict-probe",
                blame="instrument",
                observed="probe reached missing construction",
                requested="verdict testimony",
                fix="repair the verdict producer",
            )
        return real_effect(disposition, incoming)

    monkeypatch.setattr(
        disposition_module,
        "exit_disposition_effect",
        panic_on_audit_probe,
    )
    body = _completed_only(1, "body")
    exit_es = _completed_only(1, "exit")

    with arm_census() as rows:
        result = body.and_exit(exit_es, disposition=NeverSuppresses())

    assert len(result.exits) == 1
    (row,) = _rows_for(rows, "and_exit")
    assert row.verdict_probe_error is not None
    assert row.verdict_probe_error.startswith("ConstructionPanic:")
    assert row.reconciles is False
    assert totals(rows)["and_exit"]["non_reconciling"] == 1


def test_instrument_restores_every_patched_method() -> None:
    originals = {
        name: getattr(ExitSet, name)
        for name in (
            "normalize",
            "sequence",
            "and_finally",
            "and_exit",
            "and_exit_truthiness",
        )
    }

    with arm_census():
        assert getattr(ExitSet, "normalize") is not originals["normalize"]

    for name, original in originals.items():
        assert getattr(ExitSet, name) is original, f"{name} not restored"


# --------------------------------------------------------------------------
# 2. the growth law, with sequence as the control
# --------------------------------------------------------------------------


def _halted_out_by_width(site: str) -> dict[int, int]:
    """Halted arms out as the OTHER operand widens; body held fixed."""
    body = _mixed(2, "body")
    measured = {}
    for width in _WIDTHS:
        other = _mixed(width, "other")
        with arm_census() as rows:
            if site == "and_exit_truthiness":
                body.and_exit_truthiness(other, site=None)
            elif site == "and_finally":
                body.and_finally(lambda: other)
            elif site == "and_exit":
                body.and_exit(other, disposition=NeverSuppresses())
            elif site == "sequence":
                body.sequence(lambda _value: other)
            else:  # pragma: no cover - guarded by SITES
                raise AssertionError(site)
        site_rows = _rows_for(rows, site)
        _assert_all_reconcile(site_rows)
        measured[width] = sum(row.halted_out for row in site_rows)
    return measured


@pytest.mark.parametrize("site", ["and_exit", "and_finally", "and_exit_truthiness"])
def test_halted_arms_grow_with_the_other_operand(site: str) -> None:
    """The defect: the halted face is a product at all three unbypassed sites."""
    measured = _halted_out_by_width(site)

    assert measured[8] > measured[1], f"{site}: halted face did not grow: {measured}"
    # Product, not merely monotone: doubling the operand doubles the halted arms.
    for small, large in ((1, 2), (2, 4), (4, 8)):
        assert (
            measured[large] == 2 * measured[small]
        ), f"{site}: halted face is not doubling with the operand: {measured}"


def test_sequence_is_the_control_and_stays_flat() -> None:
    """``sequence``'s bypass keeps halted arms carried from incomings linear.

    The tail's own halted arms still scale -- that is the tail's face, not a
    product with the incoming halts -- so the tooth is on the split column, not
    on the total.
    """
    body = _mixed(2, "body")
    carried = {}
    for width in _WIDTHS:
        tail = _mixed(width, "tail")
        with arm_census() as rows:
            body.sequence(lambda _value: tail)
        site_rows = _rows_for(rows, "sequence")
        _assert_all_reconcile(site_rows)
        carried[width] = sum(row.halted_from_incoming for row in site_rows)

    assert len(set(carried.values())) == 1, (
        f"control moved: halted arms carried from incomings should stay flat "
        f"at |halted(self)| regardless of tail width, got {carried}"
    )
    assert carried[1] == 2, f"expected 2 halted incomings, got {carried}"


# --------------------------------------------------------------------------
# 3. the two splits that a four-cardinality row would get wrong
# --------------------------------------------------------------------------


def test_and_finally_terminal_cleanup_is_not_a_halted_arm() -> None:
    """Return-in-finally converts a halted incoming into a COMPLETION.

    A row that recorded a plain ``completed(cleanup)`` count would predict
    ``|halted(self)| x |completed(cleanup)|`` halted arms here. The true
    number is zero, because every completed cleanup is terminal.
    """
    body = _mixed(3, "body")
    cleanup = _completed_only(2, "clean")

    with arm_census() as rows:
        body.and_finally(lambda: cleanup, cleanup_restores=lambda _value: False)

    (row,) = _rows_for(rows, "and_finally")
    assert row.reconciles, row.reconcile_detail
    assert row.n_other_completed == 2
    assert row.n_other_completed_restoring == 0
    assert row.n_other_completed_terminal == 2
    assert row.halted_from_incoming == 0
    naive = row.n_incoming_halted * row.n_other_completed
    assert naive == 6, "the naive four-cardinality prediction should be nonzero here"
    assert row.halted_out == 0, (
        "every arm is a terminal completion; a plain completed(cleanup) column "
        f"would have overstated the halted face by {naive}"
    )


def test_and_finally_restoring_cleanup_does_carry_the_halted_incoming() -> None:
    """The mirror of the above: with a restoring predicate the product is real."""
    body = _mixed(3, "body")
    cleanup = _completed_only(2, "clean")

    with arm_census() as rows:
        body.and_finally(lambda: cleanup, cleanup_restores=lambda _value: True)

    (row,) = _rows_for(rows, "and_finally")
    assert row.reconciles, row.reconcile_detail
    assert row.n_other_completed_restoring == 2
    assert row.n_other_completed_terminal == 0
    assert row.halted_from_incoming == 6 == row.n_incoming_halted * 2
    assert row.halted_out == 6


def test_and_exit_halts_a_completed_incoming_against_a_completed_exit() -> None:
    """An assertion boundary halts a body that never raised.

    That halted arm comes from a (completed incoming, completed ex) pair, which
    neither ``|self| x halted(exit)`` nor ``halted(self) x completed(exit)``
    covers. The census reports it through the verdict-shape counts instead.
    """
    body = _completed_only(3, "body")
    exit_es = _completed_only(2, "exit")
    disposition = EffectBoundaryDisposition(
        matcher=EffectMatcher(kind="raise", name="ValueError"),
        unmet=_effect("AssertionError"),
    )

    with arm_census() as rows:
        body.and_exit(exit_es, disposition=disposition)

    (row,) = _rows_for(rows, "and_exit")
    assert row.reconciles, row.reconcile_detail
    assert row.n_incoming_halted == 0
    assert row.n_other_halted == 0
    # Both terms of the four-cardinality formula are zero here...
    assert row.n_incoming * row.n_other_halted == 0
    assert row.n_incoming_halted * row.n_other_completed == 0
    # ...and yet every emitted arm halts.
    assert row.n_verdict_effect == 3
    assert row.halted_from_exit == 0
    assert row.halted_from_incoming == 6
    assert row.halted_out == 6 == row.pre_len
    assert row.completed_out == 0


def test_iterations_are_recorded_separately_from_surviving_arms() -> None:
    """``pre_len`` under-reports work wherever a pair emits other than one arm."""
    body = _mixed(2, "body")
    exit_es = _completed_only(3, "exit")

    with arm_census() as rows:
        body.and_exit_truthiness(exit_es, site=None)

    (row,) = _rows_for(rows, "and_exit_truthiness")
    assert row.reconciles, row.reconcile_detail
    assert row.iterations == 4 * 3
    # Halted incomings emit two arms per pair, so arms exceed loop turns.
    assert row.pre_len == 18 > row.iterations
    assert row.post_len <= row.pre_len


def test_totals_reports_every_site() -> None:
    body = _mixed(2, "body")
    other = _mixed(2, "other")

    with arm_census() as rows:
        body.and_exit_truthiness(other, site=None)
        body.and_finally(lambda: other)
        body.and_exit(other, disposition=NeverSuppresses())
        body.sequence(lambda _value: other)

    summary = totals(rows)
    assert set(summary) == set(SITES)
    for site in SITES:
        assert summary[site]["calls"] >= 1, f"{site} never fired"
        assert summary[site]["non_reconciling"] == 0, f"{site} has broken rows"
