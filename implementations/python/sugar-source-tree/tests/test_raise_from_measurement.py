"""The raise-from census partitions syntax into direct and blocked residue."""

import importlib.util
import ast
from types import SimpleNamespace

import pytest
from pathlib import Path

from sugar_source_tree.panic import BackendDefect


SCRIPT = (
    Path(__file__).parents[2]
    / "sugar-lift-py-tests"
    / "scripts"
    / "measure_raise_from_direct_gaps.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("raise_from_measurement", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measurement_observes_raise_from_direct_residue_drained(tmp_path) -> None:
    (tmp_path / "sample.py").write_text(
        "def direct():\n"
        "    raise ValueError() from KeyError()\n\n"
        "def already_built():\n"
        "    raise ValueError()\n",
        encoding="utf-8",
    )

    result = _module().measure(tmp_path)

    assert result["syntax"] == {"raise_from": 1, "without_cause": 1, "bare": 0}
    assert result["direct"] == {}
    assert result["blocked_descendant"] == {}


def test_measurement_counts_unwritten_cause_descendant_as_blocked(tmp_path) -> None:
    (tmp_path / "blocked.py").write_text(
        "async def blocked(cause):\n"
        "    raise ValueError() from (await cause)\n",
        encoding="utf-8",
    )

    result = _module().measure(tmp_path)

    assert result["direct"] == {}
    assert result["blocked_descendant"] == {"raise_from": 1}


def test_blocked_classifier_walks_into_cause_not_up_to_parent() -> None:
    parsed = ast.parse(
        "async def blocked(cause):\n"
        "    raise ValueError() from (await cause)\n"
    )
    raise_node = next(node for node in ast.walk(parsed) if isinstance(node, ast.Raise))
    await_node = next(node for node in ast.walk(parsed) if isinstance(node, ast.Await))
    gap_sites = {("Await", await_node.lineno, await_node.col_offset)}

    direct, blocked = _module().classify_raise_from([raise_node], gap_sites, ast.unparse(parsed))

    assert direct == {}
    assert blocked == {"raise_from": 1}


def test_measurement_surfaces_planted_construction_panic(tmp_path, monkeypatch) -> None:
    path = tmp_path / "panic.py"
    path.write_text(
        "def panic(cause):\n    raise ValueError() from cause\n",
        encoding="utf-8",
    )
    module = _module()

    def planted(_path, *, reporter):
        raise BackendDefect(
            owner="planted.raise",
            observed="construction panic",
            requested="loud census result",
            fix="surface this defect",
        )

    monkeypatch.setattr(module.SourceFile, "from_path", planted)

    result = module.measure(tmp_path)

    assert result["construction_panics"] == [
        {
            "path": str(path),
            "type": "BackendDefect",
            "message": str(
                BackendDefect(
                    owner="planted.raise",
                    observed="construction panic",
                    requested="loud census result",
                    fix="surface this defect",
                )
            ),
        }
    ]
    assert module.exit_status(result) == 1


def test_measurement_is_red_when_direct_residue_remains() -> None:
    assert (
        _module().exit_status(
            {"direct": {"raise_from": 1}, "construction_panics": []}
        )
        == 1
    )


def test_gap_coordinate_failure_is_not_caught() -> None:
    class BrokenGapNode:
        kind = "Raise"

        def line_col_span(self):
            raise BackendDefect(
                owner="planted gap coordinate",
                observed="broken span",
                requested="a valid normalized coordinate",
                fix="repair the source-tree coordinate",
            )

    reporter = SimpleNamespace(gaps=[(BrokenGapNode(), object())])

    with pytest.raises(BackendDefect, match="planted gap coordinate"):
        _module().collect_gap_sites(reporter)


def test_blocked_classifier_normalizes_utf8_byte_columns() -> None:
    source = (
        "async def blocked(cause, é):\n"
        "    raise ValueError() from (é and await cause)\n"
    )
    parsed = ast.parse(source)
    raise_node = next(node for node in ast.walk(parsed) if isinstance(node, ast.Raise))
    await_node = next(node for node in ast.walk(parsed) if isinstance(node, ast.Await))
    line = source.splitlines()[await_node.lineno - 1]
    normalized_col = len(line.encode("utf-8")[: await_node.col_offset].decode("utf-8"))

    direct, blocked = _module().classify_raise_from(
        [raise_node], {("Await", await_node.lineno, normalized_col)}, source
    )

    assert direct == {}
    assert blocked == {"raise_from": 1}
