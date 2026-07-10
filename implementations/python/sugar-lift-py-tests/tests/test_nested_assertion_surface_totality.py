"""#4017 — total assertion-surface enumeration (nested if/try/except/for/with).

Corpus-wide silence: build_literal_call_report previously only walked direct
FunctionDef.body children, dropping every nested Assert. Option A: recursive
collect via SourceFragment.fragments(); each locus still goes through
_lift_assert → factory catalog → existing sugars (no new formula recognizer).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import (
    _iter_function_assertion_surfaces,
    build_literal_call_report,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_iter_function_assertion_surfaces_covers_control_flow_and_skips_nested_def() -> (
    None
):
    src = (
        "def outer(x):\n"
        "    assert True\n"
        "    if x:\n"
        "        assert not f(a)\n"
        "    try:\n"
        "        assert g()\n"
        "    except E:\n"
        "        assert h()\n"
        "    for z in zs:\n"
        "        assert i()\n"
        "    with ctx:\n"
        "        assert j()\n"
        "    def nested():\n"
        "        assert should_not_be_under_outer()\n"
        "\n"
        "def nested_top():\n"
        "    assert k()\n"
    )
    root = SourceFragment.from_source(src, "t.py")
    outer = next(
        f
        for f in root.walk()
        if f.observed == "FunctionDef" and f.function_name() == "outer"
    )
    nested = next(
        f
        for f in root.walk()
        if f.observed == "FunctionDef" and f.function_name() == "nested"
    )
    outer_lines = [a.line for a in _iter_function_assertion_surfaces(outer)]
    nested_lines = [a.line for a in _iter_function_assertion_surfaces(nested)]
    # top + if + try + except + for + with — not nested def
    assert outer_lines == [2, 4, 6, 8, 10, 12], outer_lines
    assert nested_lines == [14], nested_lines


def test_same_name_methods_each_keep_their_asserts() -> None:
    """Bare-name dig map must not drop assertion surfaces on duplicate methods.

    ``local_functions[name] = frag`` keeps one def per name; assertion
    enumeration visits every FunctionDef fragment so two ``__init__`` methods
    both contribute their asserts (#4017 name-collision totality).
    """
    src = (
        "class A:\n"
        "    def __init__(self, x):\n"
        "        if x:\n"
        "            assert not _isfinite(x)\n"
        "\n"
        "class B:\n"
        "    def __init__(self, y):\n"
        "        try:\n"
        "            pass\n"
        "        except E:\n"
        "            assert not _isfinite(y)\n"
        "\n"
        "def _isfinite(z):\n"
        "    return False\n"
    )
    report = build_literal_call_report(
        source=src, filename="dup.py", memento_file="dup.py"
    )
    assert report is not None
    not_lines = sorted(
        row.line
        for row in report.payload.factory_walk
        if row.selected == "NotSugar"
    )
    assert not_lines == [4, 11], not_lines
    disk = census_source(src, file="dup.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    assert cov.assertions.stated == 2
    assert cov.assertions.silently_unaccounted == 0


def test_nested_if_assert_not_isfinite_is_enumerated_and_warranted() -> None:
    """Structural teeth: previously silent under if → present in the report."""
    src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "def f(partials):\n"
        "    if None in partials:\n"
        "        total = partials[None]\n"
        "        assert not _isfinite(total)\n"
        "    else:\n"
        "        total = 0\n"
    )
    report = build_literal_call_report(
        source=src, filename="statistics.py", memento_file="statistics.py"
    )
    assert report is not None
    assert any(
        "assert:7:" in c.name and c.name.endswith("::assertion")
        for c in report.payload.ir
    ), [c.name for c in report.payload.ir]
    walk = [
        (row.line, row.selected, row.status) for row in report.payload.factory_walk
    ]
    assert any(
        line == 7 and selected == "NotSugar" and status == "warranted"
        for line, selected, status in walk
    ), walk

    disk = census_source(src, file="statistics.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    assert cov.assertions.stated == 1
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.lifted_cited == 1


def test_nested_except_assert_not_isfinite_is_enumerated() -> None:
    src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "def f(x):\n"
        "    try:\n"
        "        return x.as_integer_ratio()\n"
        "    except (OverflowError, ValueError):\n"
        "        assert not _isfinite(x)\n"
        "        return (x, None)\n"
    )
    report = build_literal_call_report(
        source=src, filename="statistics.py", memento_file="statistics.py"
    )
    assert report is not None
    assert any("NotSugar" == row.selected for row in report.payload.factory_walk)
    disk = census_source(src, file="statistics.py")
    cov = account_lift_coverage(disk, report.payload.to_rpc())
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.stated == 1


def test_nested_not_isfinite_bad_twin_flips_via_witness(tmp_path: Path) -> None:
    """Truthful nested ``assert not _isfinite(...)`` → SAT; lying twin → UNSAT.

    Solo-per-test (one solver invocation each). Body dig of local ``_isfinite``:
    return False makes ``assert not _isfinite(1)`` true (discharged); return True
    makes the same claim false (unsatisfied). If the nested lift were decorative,
    both twins would share a verdict — the flip proves the claim is real.
    """
    truthful_src = (
        "def _isfinite(x):\n"
        "    return False\n"
        "\n"
        "def test_nested_not_isfinite_truthful():\n"
        "    if True:\n"
        "        assert not _isfinite(1)\n"
    )
    lying_src = (
        "def _isfinite(x):\n"
        "    return True\n"
        "\n"
        "def test_nested_not_isfinite_lie():\n"
        "    if True:\n"
        "        assert not _isfinite(1)\n"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "nested-isfinite-truthful", truthful_src
    )
    t_statuses = [row.get("status") for row in truthful.prove_doc.get("rows", [])]
    assert truthful.verdict == "sat", (truthful.verdict, t_statuses)
    assert "refused" not in t_statuses
    assert any(
        "NotSugar" == name for name in truthful.selected_sugars
    ), truthful.selected_sugars

    lying = run_source_through_real_solver(
        tmp_path / "nested-isfinite-lying", lying_src
    )
    l_statuses = [row.get("status") for row in lying.prove_doc.get("rows", [])]
    assert lying.verdict == "unsat", (
        f"bad-twin must flip: truthful=sat, lying=unsat; got lying={lying.verdict}\n"
        f"truthful={truthful.verdict} {t_statuses}\n"
        f"lying={l_statuses}\n"
        f"truthful ir={truthful.lift_doc.get('ir')!r}\n"
        f"lying ir={lying.lift_doc.get('ir')!r}"
    )
