from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.lift_rpc import (
    _python_source_public_reexport_map,
    _source_contract_bridge_symbol,
)


def test_source_contract_bridge_symbol_uses_public_class_reexport_for_methods(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from project.core.api import DataFrame\n",
        encoding="utf-8",
    )
    core = package / "core"
    core.mkdir()
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "api.py").write_text(
        "from project.core.frame import DataFrame\n",
        encoding="utf-8",
    )
    (core / "frame.py").write_text(
        "class DataFrame:\n" "    def to_stata(self):\n" "        pass\n",
        encoding="utf-8",
    )

    reexports = _python_source_public_reexport_map(package)

    assert (
        _source_contract_bridge_symbol("core.frame.DataFrame.to_stata", reexports)
        == "project.DataFrame.to_stata"
    )


def test_source_contract_bridge_symbol_uses_nested_api_reexport_for_methods(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    api = package / "api" / "indexers"
    api.mkdir(parents=True)
    (package / "api" / "__init__.py").write_text(
        "from project.api import indexers\n",
        encoding="utf-8",
    )
    (api / "__init__.py").write_text(
        "from project.core.indexers.objects import VariableOffsetWindowIndexer\n",
        encoding="utf-8",
    )
    objects = package / "core" / "indexers"
    objects.mkdir(parents=True)
    (package / "core" / "__init__.py").write_text("", encoding="utf-8")
    (package / "core" / "indexers" / "__init__.py").write_text("", encoding="utf-8")
    (objects / "objects.py").write_text(
        "class VariableOffsetWindowIndexer:\n"
        "    def get_window_bounds(self):\n"
        "        pass\n",
        encoding="utf-8",
    )

    reexports = _python_source_public_reexport_map(package)

    assert (
        _source_contract_bridge_symbol(
            "core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds",
            reexports,
        )
        == "project.api.indexers.VariableOffsetWindowIndexer.get_window_bounds"
    )
