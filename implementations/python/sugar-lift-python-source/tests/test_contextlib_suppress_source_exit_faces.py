"""contextlib.suppress constructs from its source __exit__ faces.

suppress.__exit__ may halt (``raise rest`` on a residual group, a runtime
unpack of ``excinst.split``). That is not a total resource exit. It is admitted
as ``source-exit-faces`` because With re-runs the authenticated exit frame per
body face, so every exit halt supersedes the body exit as its own effect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    ExitContractV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    SourceExitFacesCompletionV1,
    _decode_protocol_resource,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
)


def _corpus(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    (root / "e.py").write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def _open(root: Path):
    clear_walk_sessions()
    return open_source_file_for_construction(
        root / "e.py",
        root=root,
        reporter=CollectingReporter(),
        source_workspace_root=root,
        resolution_session=SourceResolutionSession(
            enrolled_distributions=frozenset({"tiny-corpus", "cpython-stdlib:contextlib"})
        ),
    )


def _suppress(tmp_path, handler: str, body: str):
    source = (
        "import contextlib\n"
        "def f():\n"
        f"    with contextlib.suppress({handler}):\n"
        f"        {body}\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    ref = refs[site]
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(ref.semantics.exit.disposition, ReturnTruthinessDispositionV1)
    assert isinstance(ref.semantics.exit.completion, SourceExitFacesCompletionV1)
    assert type(with_node.sugar()) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def _halts(exits):
    return [face for face in exits.exits if isinstance(face, Halted)]


def test_suppress_consumes_the_named_exception(tmp_path):
    exits = _suppress(tmp_path, "ValueError", "raise ValueError('boom')")
    assert _halts(exits) == []
    assert any(isinstance(face, Completed) for face in exits.exits)


def test_suppress_consumes_an_authenticated_subclass(tmp_path):
    exits = _suppress(tmp_path, "LookupError", "raise KeyError('k')")
    assert _halts(exits) == []


@pytest.mark.parametrize(
    ("body", "name"),
    [
        ("raise TypeError('x')", "TypeError"),
        ("raise KeyError('k')", "KeyError"),
        ("raise KeyboardInterrupt()", "KeyboardInterrupt"),
    ],
)
def test_suppress_never_consumes_an_unrelated_exception(tmp_path, body, name):
    exits = _suppress(tmp_path, "ValueError", body)
    (halt,) = _halts(exits)
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == name


def test_suppress_completes_an_empty_body(tmp_path):
    exits = _suppress(tmp_path, "ValueError", "pass")
    assert _halts(exits) == []


def test_source_exit_faces_round_trips_and_stays_distinct_from_total():
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.context_manager_contract import EnterResultContractV1
    from sugar_lift_py_tests.ir import PrimitiveSort

    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(ReturnTruthinessDispositionV1(), SourceExitFacesCompletionV1()),
    )
    raw = json.loads(encode_jcs(semantics_to_value(semantics)))
    assert raw["exit"]["completion"] == {"kind": "source-exit-faces"}
    assert _decode_protocol_resource(raw) == semantics
    raw["exit"]["completion"] = {"kind": "partial"}
    with pytest.raises(ContextManagerContractError):
        _decode_protocol_resource(raw)
