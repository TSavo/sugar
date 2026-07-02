from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.ir import Term


def floor_to_term(value: Any, *, owner: str) -> Term:
    return value.to_term(owner=owner)
