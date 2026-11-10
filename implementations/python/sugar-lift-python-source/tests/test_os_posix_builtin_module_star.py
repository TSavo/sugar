"""``os`` resolves through ``posix`` and C calls carry a may-raise face."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from sugar_lift_python_source.dependency_export_adapter import (
    _builtin_module_star_names,
    _decided_if_test,
)
from sugar_lift_py_tests.context_manager_resolution import ContextManagerResolutionGapV1
from sugar_source_tree.nodes import With

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _prefix_and_test(source: str):
    tree = ast.parse(source)
    *prefix, node = tree.body
    assert isinstance(node, ast.If)
    return node.test, prefix


@pytest.mark.skipif("posix" not in sys.builtin_module_names, reason="posix host")
def test_builtin_module_names_membership_is_decided_from_the_interpreter() -> None:
    src = "import sys\n_names = sys.builtin_module_names\nif 'posix' in _names:\n    pass\n"
    test, prefix = _prefix_and_test(src)
    assert _decided_if_test(test, prefix) is True
    src_nt = "import sys\n_names = sys.builtin_module_names\nif 'nt' in _names:\n    pass\n"
    test, prefix = _prefix_and_test(src_nt)
    assert _decided_if_test(test, prefix) is ("nt" in sys.builtin_module_names)


def test_rebound_names_or_sys_stays_undecided() -> None:
    rebound = (
        "import sys\n_names = sys.builtin_module_names\n_names = ()\n"
        "if 'posix' in _names:\n    pass\n"
    )
    test, prefix = _prefix_and_test(rebound)
    assert _decided_if_test(test, prefix) is None
    shadow = "import sys\nsys = object()\nif 'posix' in sys.builtin_module_names:\n    pass\n"
    test, prefix = _prefix_and_test(shadow)
    assert _decided_if_test(test, prefix) is None


@pytest.mark.skipif("posix" not in sys.builtin_module_names, reason="posix host")
def test_builtin_module_star_publishes_its_runtime_public_names() -> None:
    names = _builtin_module_star_names("posix")
    assert {"getcwd", "chdir"} <= names
    assert not any(name.startswith("_") for name in names)
    # Not a builtin module: no runtime authority, nothing published.
    assert _builtin_module_star_names("json") == frozenset()


@pytest.mark.skipif("posix" not in sys.builtin_module_names, reason="posix host")
def test_contextlib_chdir_enter_may_halt_through_posix_c_calls(tmp_path: Path) -> None:
    src = 'import contextlib\ndef f():\n    with contextlib.chdir("/tmp"):\n        pass\n'
    source_file = _open(_corpus(tmp_path, src))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    # os.getcwd()/os.chdir() are posix C calls that may raise (OSError), so
    # chdir is not sealed as a total resource.
    assert type(ref) is ContextManagerResolutionGapV1
    assert ref.kind == "enter-may-halt"
    assert ref.detail == "__enter__ ExitSet"
    assert any(isinstance(node, With) for node in source_file.nodes())
