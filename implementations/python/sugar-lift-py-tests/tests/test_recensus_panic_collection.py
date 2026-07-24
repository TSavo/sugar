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


def test_recensus_projects_construction_panic_as_a_loud_counted_gap(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "fixture.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise ConstructionPanic(
            ConstructionGap(
                owner="renamed-constructor",
                blame="fixture.py:1:0",
                observed="OpaqueValue",
                requested="constructed value",
                fix="implement the constructor",
            )
        )

    import sugar_source_tree.tree as tree_mod

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", boom)
    row = module._measure_file(path, relative="fixture.py")
    assert row["category"] == "construction-panic"
    assert row["panic"]["type"] == "ConstructionPanic"


def test_control_effect_recensus_enumerates_one_file(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "clean.py"
    path.write_text("def a(z):\n    return z\n", encoding="utf-8")
    row = module._measure_file(path, relative="clean.py")
    assert row["category"] == "completed"
    assert row["functionsTotal"] == 1
    assert row["functionsClean"] == 1


def test_unresolved_with_is_typed_gap_on_enum_path(tmp_path: Path) -> None:
    module = _load("control_effect_recensus")
    path = tmp_path / "consumer.py"
    path.write_text(
        "def use_resource(manager):\n" "    with manager:\n" "        pass\n",
        encoding="utf-8",
    )
    row = module._measure_file(path, relative="consumer.py")
    # Typed loud construction, not a bare crash.
    assert row["category"] == "completed"
    assert row["functionsTotal"] == 1
    assert sum(row["families"].values()) >= 1
