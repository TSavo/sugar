"""Free-formal open EqualityFact — intentional typed factory-gap (honest limit).

Probe shape that leaves a free formal open:

  def test_a(value):
      assert sum(value) == 0

`_emit_euf_fact` refuses to construct EqualityFact when any side carries an
open term variable. Observed:

  FactoryGapEffect(
    owner=literal_call_report.equality_fact,
    observed="open term variable(s): value",
    requested="closed EqualityFact terms",
  )

Empty IR is correct — not a refuse-to-dig bug and not a fabricated binding.
Closing this requires a design choice (bind formals via fixtures/defaults,
scoped quantified EqualityFact, or hypothesis-style world). Do not paper over
with a fake refute.

Bound contrast (works today):

  def A(value):
      return sum(value)
  def test_a():
      assert A([1, 2, 3]) == 6   # arg is closed literal → EqualityFact ok
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
from sugar_lift_py_tests.factory import GapKind, GapLocus
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_FREE_ARG = (
    "def test_a(value):\n"
    "    assert sum(value) == 0\n"
)

_FREE_RHS = (
    "def test_a(expected):\n"
    "    assert sum([1, 2, 3]) == expected\n"
)

_BOUND_VIA_CALL = (
    "def A(value):\n"
    "    return sum(value)\n"
    "\n"
    "def test_a():\n"
    "    assert A([1, 2, 3]) == 6\n"
)

_BOUND_LITERAL = (
    "def test_a():\n"
    "    assert sum([1, 2, 3]) == 6\n"
)


def test_free_formal_arg_emits_open_term_factory_gap_no_equality_fact() -> None:
    """Free formal in callsite args → factory-gap, empty IR, no EqualityFact."""
    report = build_literal_call_report(
        source=_FREE_ARG,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "literal_call_report.equality_fact"
    assert effect.effect.observed == "open term variable(s): value"
    assert effect.effect.requested == "closed EqualityFact terms"
    assert effect.effect.gap_kind is GapKind.PROOFIR
    assert effect.effect.gap_locus is GapLocus.CONSTRUCTION_LAW
    assert "do not construct EqualityFact from open terms" in (
        effect.effect.fix or ""
    )


def test_free_formal_rhs_emits_open_term_factory_gap() -> None:
    """Free formal on equality RHS is the same open-term door (symmetry)."""
    report = build_literal_call_report(
        source=_FREE_RHS,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.observed == "open term variable(s): expected"


def test_bound_callsite_arg_emits_equality_fact_not_gap() -> None:
    """Closed literal arg binds the formal at the call site → EqualityFact lands."""
    report = build_literal_call_report(
        source=_BOUND_VIA_CALL,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    assert report.payload.ir, "expected EqualityFact / universe rows"
    names = [row.name for row in report.payload.ir]
    assert any("#euf#" in (n or "") for n in names), names
    open_gaps = [
        e
        for e in report.payload.effects
        if isinstance(getattr(e, "effect", None))
        and "open term variable" in (e.effect.observed or "")
    ]
    assert open_gaps == []


def test_bound_literal_sum_no_open_term_gap() -> None:
    report = build_literal_call_report(
        source=_BOUND_LITERAL,
        filename="t.py",
        memento_file="t.py",
    )
    assert report is not None
    open_gaps = [
        e
        for e in report.payload.effects
        if isinstance(getattr(e, "effect", None))
        and "open term variable" in (e.effect.observed or "")
    ]
    assert open_gaps == []


def test_bound_via_call_truthful_sat_through_real_solver(tmp_path: Path) -> None:
    """Bound path is executable; free-formal path is not silently sat-liar."""
    result = run_source_through_real_solver(tmp_path / "bound", _BOUND_VIA_CALL)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "sat", (result.verdict, statuses)
    assert "refused" not in statuses
    assert "call:sum" in repr(result.lift_doc.get("ir", [])) or "call:A" in repr(
        result.lift_doc.get("ir", [])
    )
