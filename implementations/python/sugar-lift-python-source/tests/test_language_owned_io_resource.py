"""Language-owned _io.StringIO / _io.BytesIO protocol resource.

io.py reexports both names from the C module _io, which has no authenticated
source. The twins require the documented IOBase law: a completing body
returns 1, and a ValueError in the body is not suppressed. io.open is a C
function and gets only the generic C-owned protocol, never this law.
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_python_source.resolution_session import clear_walk_sessions
from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    LanguageOwnedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete, Halted
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_language_owned_resource_sugar import (
    WithLanguageOwnedResourceSugar,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter


def _corpus(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    for name, source in files.items():
        (root / name).write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def _open(root: Path, name: str):
    clear_walk_sessions()
    return open_source_file_for_construction(
        root / name,
        root=root,
        reporter=CollectingReporter(),
        distribution="tiny-corpus",
        source_workspace_root=root,
    )


def _helpers(name: str) -> str:
    constructor = {
        "stringio": "io.StringIO()",
        "bytesio": "io.BytesIO()",
        "from_import": "StringIO()",
    }[name]
    header = (
        "from io import StringIO\n"
        if name == "from_import"
        else "import io\n"
    )
    return (
        header
        + "\n"
        + "def complete_body():\n"
        + f"    with {constructor}:\n"
        + "        return 1\n"
        + "\n"
        + "def raising_body():\n"
        + f"    with {constructor}:\n"
        + "        raise ValueError('boom')\n"
    )


def _assert_constructed(tmp_path: Path, source: str) -> None:
    root = _corpus(tmp_path, **{"t.py": source})
    source_file = _open(root, "t.py")
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    assert len(refs) == 2
    for ref in refs.values():
        assert isinstance(ref, LanguageOwnedContextManagerRefV1), ref
        assert not isinstance(ref, SourceDerivedContextManagerRefV1)
        assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
        assert not isinstance(ref.semantics, EffectBoundarySemanticsV1)
        assert isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
        assert ref.exported_name in {"StringIO", "BytesIO"}
    for node in source_file.nodes():
        if isinstance(node, With):
            sugar = node.sugar()
            assert isinstance(sugar, WithLanguageOwnedResourceSugar)
            assert not isinstance(sugar, WithSourceResourceSugar)
            assert not isinstance(sugar, WithEffectBoundarySugar)
    funcs = {
        node.name: node
        for node in source_file.nodes()
        if isinstance(node, FunctionDef) and node.name in {"complete_body", "raising_body"}
    }
    completed = funcs["complete_body"].sugar().desugar()
    assert isinstance(completed, Complete)
    assert isinstance(completed.value, UniverseValue)
    returns = [
        statement
        for statement in completed.value.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert len(returns) == 1
    assert isinstance(returns[0].value, TermValue)
    assert returns[0].value.value == 1
    raised = funcs["raising_body"].sugar().desugar()
    halted = [face for face in raised.exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, RaiseEffect)
    assert halted[0].effect.exception_name == "ValueError"


def test_stringio_never_suppresses(tmp_path) -> None:
    _assert_constructed(tmp_path, _helpers("stringio"))


def test_bytesio_never_suppresses(tmp_path) -> None:
    _assert_constructed(tmp_path, _helpers("bytesio"))


def test_from_io_import_stringio_never_suppresses(tmp_path) -> None:
    _assert_constructed(tmp_path, _helpers("from_import"))


def test_io_open_is_not_the_iobase_floor(tmp_path) -> None:
    """Lying twin: the _io floor is not a blanket enrollment of every C export.

    ``_io.open`` is a C function, so it constructs under the generic C-owned
    protocol (enter/exit may raise, exit truth decides suppression), never under
    the IOBase never-suppresses law that only StringIO/BytesIO carry.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.floor.language_owned_c_manager import (
        LanguageOwnedCManagerProtocol,
    )

    source = (
        "import io\n"
        "\n"
        "def f():\n"
        "    with io.open('/dev/null'):\n"
        "        return 1\n"
    )
    root = _corpus(tmp_path, **{"t.py": source})
    source_file = _open(root, "t.py")
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    assert len(refs) == 1
    ref = next(iter(refs.values()))
    assert isinstance(ref, LanguageOwnedContextManagerRefV1), ref
    assert type(ref.protocol) is LanguageOwnedCManagerProtocol
    assert ref.protocol.module_name == "_io"
    assert ref.target_symbol == "python:io.open"
    assert isinstance(ref.semantics.exit.disposition, ReturnTruthinessDispositionV1)
    assert not isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
