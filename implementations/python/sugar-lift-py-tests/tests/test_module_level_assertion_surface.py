"""#4024 — module-level assertion surface (Minority Report / #4016).

#4023 made assertion enumeration total over FUNCTION bodies. Module-level
asserts (direct children of Module, not inside any FunctionDef) were still
silently dropped — Crime 1 shape ``stated → ∅``. Same recursive-collect
pattern at module scope + ``fn=None`` module-parent lift (not a fake
FunctionDef). Residual proof target: pandas ``expr.py:258``.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import (
    _iter_module_assertion_surfaces,
    build_literal_call_report,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_iter_module_assertion_surfaces_covers_top_level_and_control_flow() -> None:
    src = (
        "assert True\n"
        "if x:\n"
        "    assert not f(a)\n"
        "try:\n"
        "    assert g()\n"
        "except E:\n"
        "    assert h()\n"
        "def nested():\n"
        "    assert should_not_be_module()\n"
        "class C:\n"
        "    def m(self):\n"
        "        assert also_not_module()\n"
    )
    root = SourceFragment.from_source(src, "t.py")
    lines = [a.line for a in _iter_module_assertion_surfaces(root)]
    # top + if + try + except — not nested FunctionDef / ClassDef methods
    assert lines == [1, 3, 5, 7], lines


def test_module_level_assert_only_appears_in_stated_and_lifts() -> None:
    """Tiny fixture: module-level assert only → stated, not silently dropped."""
    src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "assert not _isfinite(1)\n"
    )
    report = build_literal_call_report(
        source=src, filename="mod.py", memento_file="mod.py"
    )
    assert report is not None
    assert any(
        row.line == 4
        and row.selected == "NotSugar"
        and row.status == "warranted"
        for row in report.payload.factory_walk
    ), [(r.line, r.selected, r.status) for r in report.payload.factory_walk]
    assert any(
        m.source_function_name == "<module>"
        and m.span is not None
        and m.span.start_line == 4
        for m in report.payload.source_mementos
    ), [(m.source_function_name, m.contract_name) for m in report.payload.source_mementos]
    assert any(
        "::<module>::assert:4:" in c.name and c.name.endswith("::assertion")
        for c in report.payload.ir
    ), [c.name for c in report.payload.ir]

    disk = census_source(src, file="mod.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.lifted_cited == 1
    assert cov.assertions.silent_loci == []


def test_module_level_if_assert_is_enumerated() -> None:
    src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "if True:\n"
        "    assert not _isfinite(1)\n"
    )
    report = build_literal_call_report(
        source=src, filename="mod_if.py", memento_file="mod_if.py"
    )
    assert report is not None
    disk = census_source(src, file="mod_if.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 0
    assert any(
        row.line == 5 and row.selected == "NotSugar"
        for row in report.payload.factory_walk
    )


def test_module_level_not_isfinite_bad_twin_flips_via_witness(tmp_path: Path) -> None:
    """Truthful module ``assert not _isfinite(...)`` → SAT; lying twin → UNSAT.

    Solo-per-test. Same dig polarity as #4023 nested teeth, but parent is
    ``<module>`` not a FunctionDef.
    """
    truthful_src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "assert not _isfinite(1)\n"
    )
    lying_src = (
        "def _isfinite(x):\n"
        "    return True\n"
        "\n"
        "assert not _isfinite(1)\n"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "module-isfinite-truthful", truthful_src
    )
    t_statuses = [row.get("status") for row in truthful.prove_doc.get("rows", [])]
    assert truthful.verdict == "sat", (truthful.verdict, t_statuses)
    assert "refused" not in t_statuses
    assert any(
        "NotSugar" == name for name in truthful.selected_sugars
    ), truthful.selected_sugars

    lying = run_source_through_real_solver(
        tmp_path / "module-isfinite-lying", lying_src
    )
    l_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]
    assert lying.verdict == "unsat", (
        f"bad-twin must flip: truthful=sat, lying=unsat; got lying={lying.verdict}\n"
        f"truthful={truthful.verdict} {t_statuses}\n"
        f"lying={l_statuses}\n"
        f"truthful ir={truthful.lift_doc.get('ir')!r}\n"
        f"lying ir={lying.lift_doc.get('ir')!r}"
    )


def test_pandas_expr_py_258_module_assert_not_silently_unaccounted() -> None:
    """Residual from #4023: pandas ``expr.py:258`` must speak (not silent)."""
    import pandas

    path = Path(pandas.__file__).parent / "core" / "computation" / "expr.py"
    src = path.read_text(encoding="utf-8")
    report = build_literal_call_report(
        source=src, filename=str(path), memento_file="expr.py"
    )
    assert report is not None, "module-level residual must produce a report"

    # Line 258 is the module-body assert (parent=Module).
    walk_258 = [
        (row.selected, row.status)
        for row in report.payload.factory_walk
        if row.line == 258
    ]
    assert walk_258, "expr.py:258 must appear on factory_walk (speak)"
    assert any(
        m.source_function_name == "<module>"
        and m.span is not None
        and m.span.start_line == 258
        for m in report.payload.source_mementos
    ), "provenance must be module parent, not a fabricated FunctionDef"

    disk = census_source(src, file="expr.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    silent_at_258 = [
        locus
        for locus in cov.assertions.silent_loci
        if locus.get("line") == 258
    ]
    assert silent_at_258 == [], (
        f"expr.py:258 still silently_unaccounted: {silent_at_258}; "
        f"walk={walk_258}; silent_count={cov.assertions.silently_unaccounted}"
    )
    # Must be lifted or refused-loud — not ∅.
    assert cov.assertions.silently_unaccounted == 0 or not silent_at_258
