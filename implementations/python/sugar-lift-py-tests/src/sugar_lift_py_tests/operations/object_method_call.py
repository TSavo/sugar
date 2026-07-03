from __future__ import annotations

from typing import NoReturn, cast

from sugar_lift_py_tests.floor import FloorValue, ObjectValue
from sugar_lift_py_tests.outcome import Outcome


def call_object_method_value(
    receiver: ObjectValue,
    name: str,
    arguments: tuple[FloorValue, ...],
    *,
    owner: str,
    blame: str,
    ctx: object | None = None,
) -> Outcome:
    return cast(
        Outcome,
        receiver.call_method_value(name, arguments, owner=owner, blame=blame, ctx=ctx),
    )


def raise_object_floor_gap(
    receiver: ObjectValue,
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    receiver._floor_gap(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )
    raise AssertionError("ObjectValue._floor_gap returned")
