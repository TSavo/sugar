from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from sugar_lift_py_tests.floor import BoundVar, FloorValue
from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.dispatch_matrix_audit import (
    CellClass,
    LAW8_ANNOTATION,
    collect_dispatch_matrix,
)

EXPECTED_FLOOR_COUNT = 27
EXPECTED_OPERATION_COUNT = 32
EXPECTED_MISSING_CELL_COUNT = 741
EXPECTED_MATRIX = """\
floor | add_with | async_context_manager_with | async_iter_with | async_next_with | attribute_assign_with | attribute_delete_with | attribute_with | await_with | binary_operator_with | bitwise_with | call_method_with | construct_sequence_with | contains_with | context_manager_with | delitem_with | descriptor_with | format_value_with | guard_with | inplace_binary_operator_with | map_with | materialize_with | merge_finally_with | missing_with | next_with | project_callsite_with | project_sequence_with | reflected_binary_operator_with | route_raises_with | setitem_with | str_with | subscript_with | unary_operator_with
ArrayLiteral | I | M | M | M | M | M | M | M | I | M | I | M | I | M | M | M | M | M | R | I | M | M | M | M | I | I | M | M | M | M | I | M
BlockValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | I | R | M | M | I | M | M | I | M | M | I | M | M | M | M
BoolValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | I | M | M | M | M | M | M | M
BoundVar | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
BuilderState | I | M | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | M | R | I | I | M | M | M | R | M | M | M | M | M | M | M
Bv32Value | M | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | M | M | R | M | M | M | M | M | I | M | M | M | M | I | M | M
CallSiteValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | I | M | M | M | M | M | M | M
DictLiteralValue | M | M | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
EncodedStringValue | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
FunctionCallable | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
GuardedRaise | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
GuardedReturn | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
ImportAliasValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
LambdaCallable | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
ObjectMethodValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
ObjectValue | M | I | I | I | I | I | I | I | I | I | I | M | I | I | I | I | M | M | I | M | M | M | I | I | R | I | I | M | I | I | I | I
PredicateValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
RaiseValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
ReturnValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | I | M | M | M | M | M | M | M
SequenceConstructor | M | M | M | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
SetLiteralValue | M | M | M | M | M | M | M | M | M | M | I | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
SliceValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
StringValue | M | M | M | M | M | M | M | M | I | M | I | M | I | M | M | M | I | M | R | M | M | M | M | M | I | M | M | M | M | I | I | M
SupportValue | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | M | R | M | M | M | M | M | R | M | M | M | M | M | M | M
SymbolicValue | M | M | M | M | M | M | M | M | I | I | I | M | I | M | M | M | I | M | R | M | M | M | M | M | I | I | M | M | M | I | I | I
TermValue | I | M | M | M | M | M | M | M | I | I | I | M | M | M | M | M | I | M | R | M | M | M | M | M | I | M | M | M | M | I | M | I
TupleLiteralValue | M | M | M | M | M | M | M | M | I | M | I | M | M | M | M | M | M | M | R | M | I | M | M | M | I | I | M | M | M | M | I | M\
"""


def test_dispatch_matrix_pins_live_baseline() -> None:
    report = collect_dispatch_matrix()

    assert len(report.floor_specs) == EXPECTED_FLOOR_COUNT
    assert len(report.operation_specs) == EXPECTED_OPERATION_COUNT
    assert (
        len(report.missing_cells) == EXPECTED_MISSING_CELL_COUNT
    ), report.render_missing_cells()
    assert report.render_matrix() == EXPECTED_MATRIX


def test_planted_floor_without_operation_decisions_is_a_new_missing_cell() -> None:
    class PlantedFloor(FloorValue):
        pass

    report = collect_dispatch_matrix(extra_floor_classes=(PlantedFloor,))

    assert any(
        cell.floor == "PlantedFloor" and cell.cell_class is CellClass.MISSING
        for cell in report.missing_cells
    ), report.render_missing_cells()


def test_planted_operation_without_floor_decisions_is_a_new_missing_column() -> None:
    @dataclass(frozen=True)
    class PlantedOperation:
        method_name: ClassVar[str] = "planted_dispatch_with"

    report = collect_dispatch_matrix(extra_operation_classes=(PlantedOperation,))

    offenders = [
        cell
        for cell in report.missing_cells
        if cell.method_name == "planted_dispatch_with"
    ]
    assert offenders
    assert {cell.floor for cell in offenders} == {
        spec.name for spec in report.floor_specs
    }


def test_base_project_callsite_default_is_a_loud_refusal_not_missing() -> None:
    report = collect_dispatch_matrix()

    cell = report.cell_for(
        floor=BoundVar.__name__,
        method_name="project_callsite_with",
    )

    assert cell.cell_class is CellClass.REFUSES_LOUDLY
    assert "RefusalRecord" in cell.symptom


def test_dispatch_matrix_law8_annotation_names_rung_and_retirement() -> None:
    assert "rung: auditor" in LAW8_ANNOTATION
    assert "dunder dispatch is open" in LAW8_ANNOTATION
    assert "runtime_checkable" in LAW8_ANNOTATION


def test_dispatch_matrix_cli_reports_the_confession_vector(capsys) -> None:
    status = cli.main(["--dispatch-matrix-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "Law 8 dispatch-matrix annotation" in stdout
    assert "R(dispatch-matrix-missing-cells): 741" in stdout
    assert "BoundVar |" in stdout
