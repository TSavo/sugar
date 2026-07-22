from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import (
    NameErrorEffect,
    effect_kind,
    effect_reason,
    effect_status,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _site():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("def witness(name):\n    return name\n")
        path = f.name
    return next(SourceFile(path_source(path)).functions()).fragment


def test_name_error_effect_is_a_deterministic_incomplete_halt() -> None:
    site = _site()
    effect = NameErrorEffect(name="name", site=site)

    outcome = Incomplete(effect)

    assert outcome.effect is effect
    assert effect_status(effect) == "raise-effect"
    assert effect_kind(effect) == "RaiseEffect"
    assert "unbound name 'name'" in effect_reason(effect)
    assert effect.exception_name == "NameError"
    assert effect.occurrence == f"{site.filename}:{site.line}:{site.col}"
    assert not hasattr(effect, "runtime_operand")
