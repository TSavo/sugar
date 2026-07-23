"""Production RED instruments for With Authority v2 step 1."""

from pathlib import Path

import pytest

from with_v2_law_detector import ModuleGraph, analyze_consumer_enrollment, analyze_single_authority


PYTHON_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (
    PYTHON_ROOT / "sugar-lift-py-tests" / "src" / "sugar_lift_py_tests",
    PYTHON_ROOT / "sugar-source-tree" / "src" / "sugar_source_tree",
)


def production_graph() -> ModuleGraph:
    return ModuleGraph.from_roots(PRODUCTION_ROOTS)


def print_rows(name, rows):
    print(name, len(rows))
    for row in rows:
        print(
            f"{row.reason}: sink={row.sink_site.path}:{row.sink_site.line} "
            f"origin={row.origin_site.path}:{row.origin_site.line} "
            f"canonical={row.canonical} chain={' -> '.join(row.chain)}"
        )


@pytest.mark.xfail(strict=True, reason="current secondary With authority is migration debt")
def test_single_authority_production_debt():
    rows = analyze_single_authority(production_graph())
    print_rows("R_with_noncontract_admission_authority", rows)
    assert rows == ()


@pytest.mark.xfail(strict=True, reason="current consumer manifest enrollment is migration debt")
def test_no_consumer_enrollment_production_debt():
    rows = analyze_consumer_enrollment(production_graph())
    print_rows("R_consumer_manager_enrollment", rows)
    assert rows == ()
