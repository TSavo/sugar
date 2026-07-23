from pathlib import Path

import pytest

from sugar_lift_py_tests.cm_boundary_detector import scan_construction_boundary


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "files",
    [
        {
            "sugar/direct.py": (
                "from sugar_linker import resolve_context_manager_demand\n"
                "def sugar():\n    return resolve_context_manager_demand()\n"
            )
        },
        {
            "sugar/nested.py": (
                "from sugar_linker import resolve_context_manager_demand\n"
                "def helper():\n    return resolve_context_manager_demand()\n"
                "def sugar():\n    return helper()\n"
            )
        },
        {
            "sugar/aliased.py": (
                "import sugar_linker as hidden\n"
                "def sugar():\n    return hidden.resolve_context_manager_demand()\n"
            )
        },
        {
            "sugar/entry.py": (
                "from sugar_source_tree.outside_helper import lookup\n"
                "def sugar():\n    return lookup()\n"
            ),
            "sugar_source_tree/outside_helper.py": (
                "from sugar_linker import resolve_context_manager_demand as lookup\n"
            ),
        },
    ],
    ids=("direct", "nested-helper", "aliased-import", "outside-helper"),
)
def test_planted_boundary_violations_each_raise_r(files, tmp_path):
    for relative, source in files.items():
        _write(tmp_path, relative, source)
    report = scan_construction_boundary(
        sugar_root=tmp_path / "sugar",
        source_tree_root=tmp_path / "sugar_source_tree",
    )
    assert report.r > 0, report


def test_complete_real_roots_have_stable_zero_boundary_residue():
    python_root = Path(__file__).resolve().parents[2]
    report = scan_construction_boundary(
        sugar_root=python_root / "sugar-lift-py-tests/src/sugar_lift_py_tests/sugar",
        source_tree_root=python_root / "sugar-source-tree/src/sugar_source_tree",
    )
    assert report.files_scanned == len(list(
        (python_root / "sugar-lift-py-tests/src/sugar_lift_py_tests/sugar").rglob("*.py")
    )) + len(list(
        (python_root / "sugar-source-tree/src/sugar_source_tree").rglob("*.py")
    ))
    assert report.r == 0, report.render()
