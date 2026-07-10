"""#4025 — numpy f2py2e.py:668 residual (function-body, post-#4023).

Not an enumeration hole: assert is a direct child of ``run_compile``.
Silence was prior-assignment fold of mutator history (``sys.argv = …``)
returning an effect at the prior locus while dual-axis keys the assert
locus — Crime 1 ``stated → ∅``. Shape ``assert len(x) <= N, msg`` is owned
by ComparisonAssertionSugar when free names stay free (bare retry).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_len_lte_assert_with_msg_is_stated_and_warranted() -> None:
    """2-arg assert + len comparison shape must speak (not silently drop)."""
    src = (
        "def run_compile(flib_flags):\n"
        "    assert len(flib_flags) <= 2, repr(flib_flags)\n"
    )
    report = build_literal_call_report(
        source=src, filename="f2py2e.py", memento_file="f2py2e.py"
    )
    assert report is not None
    assert any(
        row.line == 2
        and row.selected == "ComparisonAssertionSugar"
        and row.status == "warranted"
        for row in report.payload.factory_walk
    ), [(r.line, r.selected, r.status) for r in report.payload.factory_walk]
    assert any(
        "assert:2:" in c.name and c.name.endswith("::assertion")
        for c in report.payload.ir
    ), [c.name for c in report.payload.ir]

    cov = account_lift_coverage(
        census_source(src, file="f2py2e.py"), report.payload.to_rpc()
    )
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.lifted_cited == 1
    assert cov.assertions.silent_loci == []


def test_len_lte_assert_survives_unfolderable_prior_mutator_chain() -> None:
    """f2py2e shape: mutator priors Incomplete must not silence the assert.

    Prior fold of ``sys.argv = …`` used to emit only at the prior locus;
    dual-axis then left the assert silent. Bare free-name retry owns
    ComparisonAssertionSugar for ``len(flib_flags) <= 2``.
    """
    src = (
        "import sys\n"
        "\n"
        "def run_compile():\n"
        "    sys.argv = [a for a in sys.argv if a]\n"
        "    flib_flags = [m for m in sys.argv if m.startswith('--f')]\n"
        "    assert len(flib_flags) <= 2, repr(flib_flags)\n"
    )
    report = build_literal_call_report(
        source=src, filename="f2py2e.py", memento_file="f2py2e.py"
    )
    assert report is not None
    assert any(
        row.line == 6
        and row.selected == "ComparisonAssertionSugar"
        and row.status == "warranted"
        for row in report.payload.factory_walk
    ), [(r.line, r.selected, r.status) for r in report.payload.factory_walk]

    cov = account_lift_coverage(
        census_source(src, file="f2py2e.py"), report.payload.to_rpc()
    )
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 0
    silent_at_assert = [
        loc for loc in cov.assertions.silent_loci if loc.get("line") == 6
    ]
    assert silent_at_assert == []


def test_lte_comparison_bad_twin_flips_via_witness(tmp_path: Path) -> None:
    """Truthful ``assert 1 <= 2 and True`` → sat; lying ``3 <= 2`` → unsat.

    Same ComparisonAssertionSugar door that owns ``len(x) <= N`` once free
    (``len`` is ``call:len`` over a term). BoolOp wrapper matches the catalog
    witness pair so the solver discharges; the LtE polarity is the residual shape.
    """
    truthful_src = (
        "def test_lte_truthful():\n"
        "    assert 1 <= 2 and True\n"
    )
    lying_src = (
        "def test_lte_lie():\n"
        "    assert 3 <= 2 and True\n"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "lte-truthful", truthful_src
    )
    t_statuses = [row.get("status") for row in truthful.prove_doc.get("rows", [])]
    assert truthful.verdict == "sat", (truthful.verdict, t_statuses)
    assert "refused" not in t_statuses
    assert any(
        "ComparisonAssertionSugar" == name for name in truthful.selected_sugars
    ), truthful.selected_sugars

    lying = run_source_through_real_solver(tmp_path / "lte-lying", lying_src)
    l_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]
    assert lying.verdict == "unsat", (
        f"bad-twin must flip: truthful=sat, lying=unsat; got lying={lying.verdict}\n"
        f"truthful={truthful.verdict} {t_statuses}\n"
        f"lying={l_statuses}\n"
        f"truthful ir={truthful.lift_doc.get('ir')!r}\n"
        f"lying ir={lying.lift_doc.get('ir')!r}"
    )


def test_numpy_f2py2e_668_not_silently_unaccounted() -> None:
    """Residual from #4023: f2py2e.py:668 must speak (warranted or refused-loud)."""
    import numpy.f2py.f2py2e as f2py2e

    path = Path(f2py2e.__file__)
    src = path.read_text(encoding="utf-8")
    report = build_literal_call_report(
        source=src, filename=str(path), memento_file="f2py2e.py"
    )
    assert report is not None

    walk_668 = [
        (row.selected, row.status)
        for row in report.payload.factory_walk
        if row.line == 668
    ]
    assert walk_668, "f2py2e.py:668 must appear on factory_walk (speak)"
    assert any(selected == "ComparisonAssertionSugar" for selected, _ in walk_668), (
        walk_668
    )

    cov = account_lift_coverage(
        census_source(src, file="f2py2e.py"), report.payload.to_rpc()
    )
    silent_at_668 = [
        locus for locus in cov.assertions.silent_loci if locus.get("line") == 668
    ]
    assert silent_at_668 == [], (
        f"f2py2e.py:668 still silently_unaccounted: {silent_at_668}; "
        f"walk={walk_668}; silent_count={cov.assertions.silently_unaccounted}"
    )
    assert cov.assertions.silently_unaccounted == 0 or not silent_at_668
