from __future__ import annotations

import csv
import importlib.metadata
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


def _distribution(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_resource\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def test_control_effect_recensus_runs_source_derived_preconstruction(tmp_path) -> None:
    module = _load("control_effect_recensus")
    distribution = _distribution(
        tmp_path,
        "class RenamedResource:\n"
        "    def __enter__(self):\n"
        "        return 9\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_resource():\n"
        "    return RenamedResource()\n",
    )
    consumer = (
        "import arbitrary\n"
        "def use_resource():\n"
        "    with arbitrary.make_resource():\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )
    from sugar_source_tree.nodes import With
    from sugar_source_tree.reporter import CollectingReporter

    source_file = module._production_source_file(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        distribution_index={"arbitrary": distribution},
    )

    refs = source_file.unit.construction_context.source_derived_contract_refs
    assert len(refs) == 1
    assert isinstance(next(iter(refs.values())), SourceDerivedContextManagerRefV1)
    with_node = next(node for node in source_file.nodes() if isinstance(node, With))
    assert isinstance(with_node.sugar(), WithSourceResourceSugar)
