from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from types import ModuleType

import sugar_lift_py_tests.floor as floor_package
import sugar_lift_py_tests.operations as operations_package
from sugar_lift_py_tests.floor import FloorValue

LAW8_ANNOTATION = (
    "Law 8 dispatch-matrix annotation: rung: auditor. Python cannot climb this "
    "higher today because dunder dispatch is open and there is no coherence "
    "checker tying every FloorValue subclass to every operation method_name at "
    "registration. Retirement condition: if the floor surface becomes "
    "protocol-classed with runtime_checkable enforcement at registration, this "
    "auditor retires."
)


class CellClass(Enum):
    IMPLEMENTED = "implemented"
    REFUSES_LOUDLY = "refuses-loudly"
    MISSING = "missing"


@dataclass(frozen=True)
class FloorSpec:
    name: str
    cls: type[FloorValue]

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "module": self.cls.__module__}


@dataclass(frozen=True)
class OperationSpec:
    method_name: str
    operation_classes: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "method_name": self.method_name,
            "operation_classes": list(self.operation_classes),
        }


@dataclass(frozen=True)
class DispatchMatrixCell:
    floor: str
    method_name: str
    operation_classes: tuple[str, ...]
    cell_class: CellClass
    owner: str
    symptom: str

    def to_json(self) -> dict[str, object]:
        return {
            "floor": self.floor,
            "method_name": self.method_name,
            "operation_classes": list(self.operation_classes),
            "cell_class": self.cell_class.value,
            "owner": self.owner,
            "symptom": self.symptom,
        }


@dataclass(frozen=True)
class DispatchMatrixReport:
    floor_specs: tuple[FloorSpec, ...]
    operation_specs: tuple[OperationSpec, ...]
    cells: tuple[DispatchMatrixCell, ...]

    @property
    def missing_cells(self) -> tuple[DispatchMatrixCell, ...]:
        return tuple(
            cell for cell in self.cells if cell.cell_class is CellClass.MISSING
        )

    @property
    def refuses_loudly_cells(self) -> tuple[DispatchMatrixCell, ...]:
        return tuple(
            cell
            for cell in self.cells
            if cell.cell_class is CellClass.REFUSES_LOUDLY
        )

    @property
    def implemented_cells(self) -> tuple[DispatchMatrixCell, ...]:
        return tuple(
            cell for cell in self.cells if cell.cell_class is CellClass.IMPLEMENTED
        )

    @property
    def r_dispatch_matrix_missing_cells(self) -> int:
        return len(self.missing_cells)

    @property
    def is_stable(self) -> bool:
        return self.r_dispatch_matrix_missing_cells == 0

    def cell_for(self, *, floor: str, method_name: str) -> DispatchMatrixCell:
        for cell in self.cells:
            if cell.floor == floor and cell.method_name == method_name:
                return cell
        raise KeyError(f"{floor}.{method_name}")

    def render_missing_cells(self) -> str:
        lines = [
            "R(dispatch-matrix-missing-cells): "
            f"{self.r_dispatch_matrix_missing_cells}",
        ]
        for cell in self.missing_cells:
            operations = ",".join(cell.operation_classes)
            lines.append(
                f"- {cell.floor}.{cell.method_name} "
                f"operation={operations} owner={cell.owner} symptom={cell.symptom}"
            )
        return "\n".join(lines)

    def render_matrix(self) -> str:
        header = ["floor", *[spec.method_name for spec in self.operation_specs]]
        rows = [" | ".join(header)]
        for floor in self.floor_specs:
            marks = [
                _matrix_mark(self.cell_for(floor=floor.name, method_name=spec.method_name))
                for spec in self.operation_specs
            ]
            rows.append(" | ".join((floor.name, *marks)))
        return "\n".join(rows)

    def to_json(self) -> dict[str, object]:
        return {
            "law8_annotation": LAW8_ANNOTATION,
            "floor_count": len(self.floor_specs),
            "operation_count": len(self.operation_specs),
            "implemented_cells": len(self.implemented_cells),
            "refuses_loudly_cells": len(self.refuses_loudly_cells),
            "R(dispatch-matrix-missing-cells)": len(self.missing_cells),
            "floor_specs": [spec.to_json() for spec in self.floor_specs],
            "operation_specs": [spec.to_json() for spec in self.operation_specs],
            "cells": [cell.to_json() for cell in self.cells],
        }


_BASE_REFUSAL_METHODS = {
    "project_callsite_with": (
        "FloorValue.project_callsite_with routes to "
        "CallsiteProjectionOperation.project_unknown, which raises the typed "
        "RefusalRecord dig-refusal diagnostic instead of silently defaulting."
    ),
    "inplace_binary_operator_with": (
        "FloorValue.inplace_binary_operator_with routes to "
        "InplaceBinaryOperatorOperation.inplace_default, which re-dispatches to "
        "the concrete binary or bitwise operation instead of silently defaulting."
    ),
}


def collect_dispatch_matrix(
    *,
    extra_floor_classes: Iterable[type[FloorValue]] = (),
    extra_operation_classes: Iterable[type[object]] = (),
) -> DispatchMatrixReport:
    floor_specs = _collect_floor_specs(extra_floor_classes)
    operation_specs = _collect_operation_specs(extra_operation_classes)
    cells = tuple(
        _classify_cell(floor_spec=floor_spec, operation_spec=operation_spec)
        for floor_spec in floor_specs
        for operation_spec in operation_specs
    )
    return DispatchMatrixReport(
        floor_specs=floor_specs,
        operation_specs=operation_specs,
        cells=cells,
    )


def render_text(report: DispatchMatrixReport) -> str:
    return "\n".join(
        (
            LAW8_ANNOTATION,
            f"floors: {len(report.floor_specs)}",
            f"dispatch-names: {len(report.operation_specs)}",
            f"implemented-cells: {len(report.implemented_cells)}",
            f"refuses-loudly-cells: {len(report.refuses_loudly_cells)}",
            (
                "R(dispatch-matrix-missing-cells): "
                f"{report.r_dispatch_matrix_missing_cells}"
            ),
            "legend: I=implemented R=refuses-loudly M=missing",
            report.render_matrix(),
            report.render_missing_cells(),
            "",
        )
    )


def _collect_floor_specs(
    extra_floor_classes: Iterable[type[FloorValue]],
) -> tuple[FloorSpec, ...]:
    classes: dict[str, type[FloorValue]] = {}
    for cls in _iter_classes(floor_package):
        if cls is FloorValue:
            continue
        if issubclass(cls, FloorValue):
            classes[cls.__name__] = cls
    for cls in extra_floor_classes:
        classes[cls.__name__] = cls
    return tuple(FloorSpec(name=name, cls=classes[name]) for name in sorted(classes))


def _collect_operation_specs(
    extra_operation_classes: Iterable[type[object]],
) -> tuple[OperationSpec, ...]:
    by_method: dict[str, set[str]] = {}
    for cls in (*tuple(_iter_classes(operations_package)), *extra_operation_classes):
        method_name = getattr(cls, "method_name", None)
        if not isinstance(method_name, str):
            continue
        by_method.setdefault(method_name, set()).add(cls.__name__)
    return tuple(
        OperationSpec(
            method_name=method_name,
            operation_classes=tuple(sorted(by_method[method_name])),
        )
        for method_name in sorted(by_method)
    )


def _iter_classes(package: ModuleType) -> Iterable[type[object]]:
    prefix = package.__name__ + "."
    package_paths = getattr(package, "__path__", ())
    for module_info in pkgutil.iter_modules(package_paths, prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                yield cls


def _classify_cell(
    *,
    floor_spec: FloorSpec,
    operation_spec: OperationSpec,
) -> DispatchMatrixCell:
    method_name = operation_spec.method_name
    floor_cls = floor_spec.cls
    owner = f"{floor_spec.name}.{method_name}"
    if method_name in floor_cls.__dict__:
        return DispatchMatrixCell(
            floor=floor_spec.name,
            method_name=method_name,
            operation_classes=operation_spec.operation_classes,
            cell_class=CellClass.IMPLEMENTED,
            owner=owner,
            symptom=(
                f"{floor_spec.name} declares {method_name}; "
                "perform_operation dispatches to that floor-owned arm."
            ),
        )
    if _inherits_base_refusal(floor_cls, method_name):
        return DispatchMatrixCell(
            floor=floor_spec.name,
            method_name=method_name,
            operation_classes=operation_spec.operation_classes,
            cell_class=CellClass.REFUSES_LOUDLY,
            owner=owner,
            symptom=_BASE_REFUSAL_METHODS[method_name],
        )
    return DispatchMatrixCell(
        floor=floor_spec.name,
        method_name=method_name,
        operation_classes=operation_spec.operation_classes,
        cell_class=CellClass.MISSING,
        owner=owner,
        symptom=(
            "perform_operation would first discover this cell at dig time as a "
            f"FactoryGap requesting {method_name} on {floor_spec.name}; #3355 "
            "showed these undecided cells become witness-time lying-SAT residues "
            "when the missing arm should have emitted derived testimony."
        ),
    )


def _inherits_base_refusal(floor_cls: type[FloorValue], method_name: str) -> bool:
    base_method = FloorValue.__dict__.get(method_name)
    if base_method is None or method_name not in _BASE_REFUSAL_METHODS:
        return False
    return getattr(floor_cls, method_name, None) is base_method


def _matrix_mark(cell: DispatchMatrixCell) -> str:
    if cell.cell_class is CellClass.IMPLEMENTED:
        return "I"
    if cell.cell_class is CellClass.REFUSES_LOUDLY:
        return "R"
    if cell.cell_class is CellClass.MISSING:
        return "M"
    raise AssertionError(f"unhandled dispatch matrix cell class: {cell.cell_class}")
