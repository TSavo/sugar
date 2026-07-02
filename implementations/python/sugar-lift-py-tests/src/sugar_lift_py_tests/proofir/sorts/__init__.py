from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import (
    Bool,
    FunctionSort as IrFunctionSort,
    Int,
    PrimitiveSort,
    Real,
    Sort as IrSort,
    String,
)

from sugar_lift_py_tests.proofir._errors import proofir_construction_gap


@dataclass(frozen=True, eq=False)
class Sort:
    name: str
    ir_sort: IrSort

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Sort) and self.ir_sort == other.ir_sort

    def __hash__(self) -> int:
        return hash(repr(self.ir_sort))

    def is_explicitly_coercible_to(self, other: "Sort") -> bool:
        return self == other


class IntSort(Sort):
    def __init__(self) -> None:
        super().__init__(name="Int", ir_sort=Int())


class RealSort(Sort):
    def __init__(self) -> None:
        super().__init__(name="Real", ir_sort=Real())


class BoolSort(Sort):
    def __init__(self) -> None:
        super().__init__(name="Bool", ir_sort=Bool())


class StringSort(Sort):
    def __init__(self) -> None:
        super().__init__(name="String", ir_sort=String())


@dataclass(frozen=True, eq=False)
class FunctionSort(Sort):
    args: tuple[Sort, ...]
    return_sort: Sort

    def __init__(self, args: tuple[Sort, ...], return_sort: Sort) -> None:
        super().__init__(
            name="Function",
            ir_sort=IrFunctionSort(
                tuple(arg.ir_sort for arg in args),
                return_sort.ir_sort,
            ),
        )
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "return_sort", return_sort)


def sort_from_ir(ir_sort: IrSort) -> Sort:
    if isinstance(ir_sort, PrimitiveSort):
        if ir_sort.name == "Int":
            return IntSort()
        if ir_sort.name == "Real":
            return RealSort()
        if ir_sort.name == "Bool":
            return BoolSort()
        if ir_sort.name == "String":
            return StringSort()
    if isinstance(ir_sort, IrFunctionSort):
        return FunctionSort(
            tuple(sort_from_ir(arg) for arg in ir_sort.args),
            sort_from_ir(ir_sort.return_),
        )
    proofir_construction_gap(
        owner="proofir.sorts",
        observed=repr(ir_sort),
        requested="known tiny ProofIR Sort",
        fix="add a tiny proofir/sorts wrapper before crossing the construction boundary",
    )


__all__ = [
    "BoolSort",
    "FunctionSort",
    "IntSort",
    "RealSort",
    "Sort",
    "StringSort",
    "sort_from_ir",
]
