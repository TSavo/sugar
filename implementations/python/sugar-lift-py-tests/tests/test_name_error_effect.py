from __future__ import annotations

from dataclasses import asdict
import tempfile

from sugar_lift_py_tests.effect import (
    NameErrorEffect,
    TypeErrorRuntimeEffect,
    effect_kind,
    effect_reason,
    effect_status,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _site():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("def witness(name):\n    return name\n")
        path = f.name
    return next(SourceFile(path_source(path)).functions()).fragment


def test_name_error_effect_is_incomplete_carryable_like_type_error_peer() -> None:
    site = _site()
    evidence = runtime_effect_evidence("python:name_read", make_var("name"), site)
    effect = NameErrorEffect("unbound name read", **evidence)
    peer = TypeErrorRuntimeEffect("invalid runtime type", **evidence)

    outcome = Incomplete(effect)

    assert outcome.effect is effect
    assert effect.kind() is NameErrorEffect
    assert effect_status(effect) == effect_status(peer) == "runtime-effect"
    assert effect_kind(effect) == effect_kind(peer) == "RuntimeEffect"
    assert effect_reason(effect) == "unbound name read"
    assert asdict(effect).keys() == asdict(peer).keys()
    assert effect.witness.site is site
