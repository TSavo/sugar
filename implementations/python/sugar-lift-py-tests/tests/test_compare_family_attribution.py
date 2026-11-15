from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.no_call_body_attribution import (
    AttributionOutcome,
    BodyProbe,
    ProducerFamily,
    attribute_body_probe,
    run_authenticated_attribution,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Compare
from sugar_source_tree.tree import SourceFile


from sugar_lift_py_tests.repo_root import resolve_repo_root


def test_call_operand_raise_is_owned_by_call_not_compare_root() -> None:
    """LYING TWIN: root shape cannot steal a pre-comparison Call halt."""
    source = (
        "def fail():\n"
        "    raise ValueError()\n"
        "def check():\n"
        "    with boundary(ValueError):\n"
        "        fail() == 1\n"
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "compare_call_owner.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))

    attributed = attribute_body_probe(
        BodyProbe(
            body_id="compare_call_owner.py:5:Compare",
            family=ProducerFamily.COMPARE,
            evaluator=lambda: compare.sugar().desugar(None),
        )
    )

    assert attributed.outcome is AttributionOutcome.AUTHENTICATED_EXIT
    assert attributed.detail == "Call"
    assert attributed.body_id == "compare_call_owner.py:5:Compare"


def test_authenticated_compare_population_has_closed_three_outcome_split() -> None:
    repo_root = resolve_repo_root()
    report = run_authenticated_attribution(
        repo_root, families=frozenset({ProducerFamily.COMPARE})
    )
    row = report.by_family[ProducerFamily.COMPARE]

    print(report.render())
    assert row.enrolled == 181
    assert (
        row.authenticated_exceptional_exits
        + row.named_refusals
        + row.construction_panics
        == 181
    )
    assert report.discrepancies == ()
    assert row.construction_panics == 0
