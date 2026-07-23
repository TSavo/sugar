from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "script_name",
    ("comprehension_iteration_recensus", "control_effect_recensus"),
)
def test_recensus_projects_construction_panic_as_a_loud_counted_gap(
    script_name: str,
) -> None:
    module = _load(script_name)
    panic = ConstructionPanic(
        ConstructionGap(
            owner="renamed-constructor",
            blame="fixture.py:1:0",
            observed="OpaqueValue",
            requested="constructed value",
            fix="implement the constructor",
        )
    )

    def panic_walker():
        raise panic

    value, row = module._collect_file_construction("fixture.py", panic_walker)

    assert value is None
    assert row == {
        "file": "fixture.py",
        "type": "ConstructionPanic",
        "message": panic.info.message,
        "gap": panic.info.to_json(),
    }
