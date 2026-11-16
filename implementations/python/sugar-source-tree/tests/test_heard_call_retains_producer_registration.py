"""A roll that hears a call another roll built reads that roll's registration.

A memo row is served to every reporter that asks, and its testimony is
replayed to one that has not heard it (``construction_cache.serve``).  The
row's nodes were built under the reporter that computed it, and the call
reconciled its definition with that reporter's roll.  A second testimony
reporter hearing the row asked its own roll for those refs and refused the
call by ``definition-ref-not-materialized`` (seven pandas board files, CI run
43667269574: ``tests/frame/constructors/test_from_records.py``,
``tests/frame/methods/test_to_csv.py``, ``tests/frame/test_subclass.py``,
``tests/internals/test_internals.py``, ``tests/io/formats/test_format.py``,
``tests/tseries/offsets/test_fiscal.py``, ``util/_print_versions.py``).

Truthful twin: the hearing roll retains the registrations of the roll that
built the call, and the call testifies.  Lying twin: a definition no roll
registered is retained nowhere and stays refused by the same name.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import NULL_REPORTER, CollectingReporter


def _seated(call, definition):
    """The call-site sugar that names its definition occurrence.

    Its one producer is a call at its definition's recursion seat
    (``Call._recursion_seat_call``): a call of a same-file ``def`` anywhere
    else is that function value's application (``Call._function_value_call``,
    #8958) and names no definition occurrence, so ``call.sugar()`` no longer
    hands one over.  The seat's sugar is built here at the call's own
    occurrence, the coordinate its construction minted, so what the hearing
    roll is asked is exactly what a seated call presents."""
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

    return CallSiteSugar(
        target_name=call.func.id,
        args=(),
        site=call.fragment,
        call_occurrence=call._construct_sugar().call_occurrence,
        expected_definition_ref=definition,
    )


def _computing_and_hearing_rolls(tmp_path):
    """One file, the call built under one testimony roll, and a second
    testimony roll that built nothing."""
    path = tmp_path / "heard.py"
    path.write_text(
        "def helper(value):\n"
        "    return value\n\n"
        "def caller(value):\n"
        "    return helper(value)\n"
    )
    collector = CollectingReporter()
    source = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=collector,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    computing = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, computing)
    call = next(
        node
        for node in root.walk()
        if isinstance(node, Call) and node.segment() == "helper(value)"
    )
    hearing = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == "helper"
    )
    return source, call, hearing, _seated(call, definition)


def test_a_heard_call_testifies_through_the_computing_rolls_registration(
    tmp_path,
) -> None:
    _source, call, hearing, sugar = _computing_and_hearing_rolls(tmp_path)
    definition = sugar.expected_definition_ref
    # The hearing roll built neither occurrence.
    assert hearing.materialized_node_for_ref(call.ref) is None
    assert hearing.materialized_node_for_ref(definition.ref) is None

    # What a served memo row replays into a reporter that has not heard it.
    hearing.present_construction(call, sugar)

    assert hearing.materialized_node_for_ref(call.ref) is not None
    assert hearing.materialized_node_for_ref(definition.ref) is not None
    assert hearing.testimony_for(call) is not None


def _retentions(monkeypatch) -> list:
    """Every write through the one retention door from here on, as
    ``(roll, backend ref, producer)``."""
    door = ConstructionTestimonyReporterV1.retain_registered_node_from
    seen: list = []

    def spy(self, node, producer):
        retained = door(self, node, producer)
        seen.append((self, retained.ref, producer))
        return retained

    monkeypatch.setattr(
        ConstructionTestimonyReporterV1, "retain_registered_node_from", spy
    )
    return seen


def test_a_heard_occurrence_is_retained_through_the_one_retention_door(
    tmp_path, monkeypatch
) -> None:
    """One writer of a registration a roll did not construct: the hearing
    roll's two retentions are writes of ``retain_registered_node_from``, the
    door a call's construction writes its definition through."""
    _source, call, hearing, sugar = _computing_and_hearing_rolls(tmp_path)
    definition = sugar.expected_definition_ref
    seen = _retentions(monkeypatch)

    hearing.present_construction(call, sugar)

    assert (hearing, definition.ref, definition.reporter) in seen
    assert (hearing, call.ref, call.reporter) in seen
    assert len(seen) == 2


def test_a_definition_no_roll_registered_stays_refused_by_name(
    tmp_path, monkeypatch
) -> None:
    source, call, hearing, sugar = _computing_and_hearing_rolls(tmp_path)
    # The same definition, born under a reporter that owns no registration.
    unregistered = materialize(
        source.unit, sugar.expected_definition_ref.ref, NULL_REPORTER
    )
    lying = replace(sugar, expected_definition_ref=unregistered)
    seen = _retentions(monkeypatch)

    with pytest.raises(
        ConstructedValueTestimonyNotWritten,
        match="definition-ref-not-materialized",
    ):
        hearing.present_construction(call, lying)
    assert hearing.materialized_node_for_ref(unregistered.ref) is None
    # It was handed to no door: nothing is retained for it, by any writer.
    assert all(ref != unregistered.ref for _roll, ref, _producer in seen)
