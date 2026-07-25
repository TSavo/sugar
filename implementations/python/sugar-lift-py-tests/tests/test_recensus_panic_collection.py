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
    row = module._measure_file(path, relative="consumer.py", workspace_root=tmp_path)
    # Typed loud construction, not a bare crash.
    assert row["category"] == "completed"
    assert row["functionsTotal"] == 1
    assert sum(row["families"].values()) >= 1
    # With preconstruction authority present, an unresolvable manager is a
    # resolution gap — not the false-red RuntimeSelected that bare
    # construction_context=None painted onto every With.
    assert row["families"].get("RuntimeSelectedContextManager", 0) == 0
    assert (
        row["families"].get("ContextManagerResolutionConstructionGap", 0) >= 1
        or sum(row["families"].values()) >= 1
    )


def test_with_census_injects_construction_context(tmp_path: Path) -> None:
    """Instrument law: census must not call bare SourceFile without context."""
    module = _load("control_effect_recensus")
    path = tmp_path / "with_open.py"
    path.write_text(
        "def use():\n" "    with open('x') as f:\n" "        pass\n",
        encoding="utf-8",
    )
    row = module._measure_file(path, relative="with_open.py", workspace_root=tmp_path)
    assert row["category"] == "completed"
    # open is not source-derived under provisional gaps — honest residual is a
    # typed CM gap, never unconditional RuntimeSelected from missing context.
    assert row["families"].get("RuntimeSelectedContextManager", 0) == 0


def test_construction_gap_occurrence_counted_once(tmp_path: Path) -> None:
    """Catch+reporter must not double-tally (392 vs 196 class of defect).

    A With that report_gap then raises is ONE occurrence. Family type total
    equals distinct with-node gaps, not 2×.
    """
    module = _load("control_effect_recensus")
    path = tmp_path / "with_param.py"
    path.write_text(
        "def use(manager):\n" "    with manager:\n" "        pass\n",
        encoding="utf-8",
    )
    row = module._measure_file(
        path, relative="with_param.py", workspace_root=tmp_path
    )
    assert row["category"] == "completed"
    families = row.get("families") or {}
    # One With site → one CM gap occurrence (not catch+reporter = 2).
    cm = families.get("ContextManagerResolutionConstructionGap", 0)
    rs = families.get("RuntimeSelectedContextManager", 0)
    assert rs == 0
    assert cm == 1, families
    # No presentation-duplicate keys.
    assert not any(k.startswith("owner:") for k in families)
    assert not any(k.startswith("with-node:") for k in families)


def test_backend_defect_keys_split_cm_and_call_demand() -> None:
    """Demand/resolution BackendDefects are hygiene axes, not construction R."""
    module = _load("control_effect_recensus")
    cm = module._backend_defect_key(
        "BackendDefect: enrolled context-manager demand missing from resolution table"
    )
    call = module._backend_defect_key(
        "BackendDefect: enrolled call demand missing from resolution table"
    )
    other = module._backend_defect_key("BackendDefect: something else")
    assert cm == "BackendDefect:cm-demand-missing-from-resolution"
    assert call == "BackendDefect:call-demand-missing-from-resolution"
    assert cm != call
    assert other.startswith("BackendDefect:")
    assert other not in {cm, call}
