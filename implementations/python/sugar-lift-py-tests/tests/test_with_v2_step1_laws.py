"""Production RED instruments for With Authority v2 step 1.

The single-authority law (``R_with_noncontract_admission_authority``: a
``with`` admits its success only through a context-manager contract ref) has
no production subject since #8491: a ``with`` constructs from its head alone,
the manager the head reduces to, and the contract-ref admission door it
policed is deleted.  Its detector stays pinned on its planted cases
(``test_with_v2_fixture_truth_set``); production is not asked for a door
that does not exist.
"""

from with_v2_law_detector import (
    ModuleGraph,
    analyze_consumer_enrollment,
)

from sugar_lift_py_tests.repo_root import python_implementations_root

PYTHON_ROOT = python_implementations_root()
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


def test_no_consumer_enrollment_production_is_zero():
    rows = analyze_consumer_enrollment(production_graph())
    print_rows("R_consumer_manager_enrollment", rows)
    assert rows == ()
