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

    # #7757 step 5 (#8705, "Edge, join at prove"): ``fail()`` is its
    # coordinate and edge, never ``fail``'s body applied at the call, so its
    # halt names no exception here (``fail``'s contract states the
    # ``ValueError``; prove types it, #8749).  Before #8705 this read the
    # ``ValueError`` off the applied body (``AUTHENTICATED_EXIT``, owner
    # ``Call``).  The root still never steals the call's halt: no face of the
    # comparison names the ``ValueError`` as its own.
    assert attributed.outcome is AttributionOutcome.UNDISCHARGED
    assert attributed.body_id == "compare_call_owner.py:5:Compare"
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    value_error = (
        TemporalContext.empty().value_for("ValueError").exception_type_identity()
    )
    coordinates = attributed.exceptional_exit_coordinates
    assert coordinates
    assert all(coordinate != value_error for coordinate, _occurrence in coordinates)


def test_authenticated_compare_population_has_a_closed_exit_split() -> None:
    """Every enrolled body ends on one arm, and no arm is a panic.

    Each probe reduces its ``with`` body's comparison with no context, so its
    operands are undecided (``left < right`` on two formals,
    ``test_pandas_compare_caller_twins``), and a comparison of undecided
    operands dispatches to ``__lt__``/``__gt__``/... of a type nothing here
    decides: it may raise an exception whose type nothing here decides.  That
    raise is never dropped and never named a type it is not: the body is
    undischarged, and its nameless face is stated by name in the identity
    list, as the attribute family's are
    (``test_authenticated_attribute_family_has_a_closed_exit_split``).  No
    count of authenticated exits is demanded."""
    from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome

    repo_root = resolve_repo_root()
    report = run_authenticated_attribution(
        repo_root, families=frozenset({ProducerFamily.COMPARE})
    )
    row = report.by_family[ProducerFamily.COMPARE]

    print(report.render())
    assert row.enrolled == 181
    assert row.outcome_total == 181
    assert row.construction_panics == 0
    assert report.discrepancies == ()
    assert report.conservation_shortfall == 0
    undischarged = {
        body.body_id
        for body in report.bodies
        if body.outcome is AttributionOutcome.UNDISCHARGED
    }
    assert len(undischarged) == row.undischarged
    assert {
        discrepancy.body_id
        for discrepancy in report.exceptional_exit_identity_discrepancies
    } == undischarged
