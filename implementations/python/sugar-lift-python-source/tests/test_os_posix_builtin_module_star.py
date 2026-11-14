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
from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    SourceEnterFacesCompletionV1,
    SourceExitFacesCompletionV1,
)
from sugar_lift_py_tests.context_manager_resolution import SourceDerivedContextManagerRefV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With

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
def test_contextlib_chdir_constructs_with_posix_c_call_faces(tmp_path: Path) -> None:
    src = 'import contextlib\ndef f():\n    with contextlib.chdir("/tmp"):\n        pass\n'
    source_file = _open(_corpus(tmp_path, src))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics.enter.completion, SourceEnterFacesCompletionV1)
    assert isinstance(ref.semantics.exit.completion, SourceExitFacesCompletionV1)
    assert isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
    with_node = next(node for node in source_file.nodes() if isinstance(node, With))
    assert type(with_node.sugar()) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    assert any(isinstance(face, Completed) for face in exits)
    halted = [face for face in exits if isinstance(face, Halted)]
    # os.getcwd() and os.chdir(path) in __enter__, os.chdir(pop()) in __exit__:
    # each posix call has no Python body behind it, so it is not bridged and
    # is never asked what it is written in (#7757 item 3). The pop reads
    # ``self._old_cwd`` through ``self``, whose contents at the exit are not
    # testified there, so it is two-faced too.
    assert all(isinstance(face.effect, UndeterminedRaiseEffect) for face in halted)
    owners = {face.effect.producer_node_owner for face in halted}
    assert "BuiltinMethodCall:list.pop" in owners
    assert not any(owner.startswith("LanguageOwned") for owner in owners)


def test_enter_completion_round_trips_through_contract_json() -> None:
    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ProtocolResourceSemanticsV1,
        _decode_protocol_resource,
        semantics_to_value,
    )
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import PrimitiveSort
    import json

    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value"), SourceEnterFacesCompletionV1()),
        ExitContractV1(NeverSuppressesDispositionV1()),
    )
    raw = json.loads(encode_jcs(semantics_to_value(semantics)))
    assert raw["enter"]["completion"] == {"kind": "source-enter-faces"}
    assert _decode_protocol_resource(raw) == semantics
