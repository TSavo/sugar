from __future__ import annotations

from sugar_lift_py_tests.floor import BoolValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import Formula, bool_const, eq, ne, num
from sugar_lift_py_tests.operations import MethodCallOperation, perform_operation
from sugar_lift_py_tests.outcome import complete_value


def object_truth_formula(
    value: ObjectValue,
    ctx,
    *,
    owner: str,
    blame: str,
) -> Formula:
    if value.has_method("__bool__"):
        bool_value = _force_dunder(value, ctx, "__bool__", owner=owner, blame=blame)
        if not isinstance(bool_value, BoolValue):
            raise TypeError(f"{owner} __bool__ must reduce to BoolValue")
        return eq(bool_const(bool_value.value), bool_const(True))

    len_value = _force_dunder(value, ctx, "__len__", owner=owner, blame=blame)
    if not isinstance(len_value, TermValue):
        raise TypeError(f"{owner} __len__ must reduce to TermValue")
    if not isinstance(len_value.value, int) or isinstance(len_value.value, bool):
        raise TypeError(f"{owner} __len__ must reduce to an int TermValue")
    return ne(num(len_value.value), num(0))


def _force_dunder(
    value: ObjectValue,
    ctx,
    name: str,
    *,
    owner: str,
    blame: str,
):
    outcome = perform_operation(
        owner=owner,
        blame=blame,
        receiver=value,
        operation=MethodCallOperation(
            name=name,
            arguments=(),
            owner=owner,
            blame=blame,
        ),
        ctx=ctx,
    )
    return force_floor(
        complete_value(outcome, owner=f"{owner} {name}"),
        ctx,
        owner=f"{owner} {name}",
    )
