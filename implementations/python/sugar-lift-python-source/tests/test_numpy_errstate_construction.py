"""``with numpy.errstate()`` constructs from source plus the Cut 2 floors."""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    SourceEnterFacesCompletionV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete, Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
)


ERRSTATE = (
    "import numpy as np\n"
    "\n"
    "def f():\n"
    "    with np.errstate(divide='ignore'):\n"
    "        return 1\n"
)

ERRSTATE_RAISE = (
    "import numpy as np\n"
    "\n"
    "def f():\n"
    "    with np.errstate(divide='ignore'):\n"
    "        raise RuntimeError('boom')\n"
)


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


def _open(root: Path, name: str, *, session):
    clear_walk_sessions()
    return open_source_file_for_construction(
        root / name,
        root=root,
        reporter=CollectingReporter(),
        source_workspace_root=root,
        resolution_session=session,
    )


def _with_resolution(root: Path, name: str, *, session):
    source_file = _open(root, name, session=session)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    return refs[site]


def test_unenrolled_errstate_stays_call_target_off_population(tmp_path) -> None:
    """The code imports numpy, so this membrane control does not pass
    ``distribution`` into populate (that door would widen the population)."""
    from sugar_lift_py_tests.canonicalizer import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_source_tree.tree import SourceFile

    root = _corpus(tmp_path, **{"e.py": ERRSTATE})
    path = root / "e.py"
    source = path.read_text(encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({"tiny-corpus"})
        ),
    )
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert type(ref) is OpaqueCitedContextManagerRefV1
    assert ref.roster.resolution_kind == "call-target-off-population"
    assert ref.roster.target_name == "python:numpy.errstate"


def test_enrolled_errstate_constructs_with_its_c_call_enter_faces(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": ERRSTATE})
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
    )
    ref = _with_resolution(root, "e.py", session=session)
    # errstate.__enter__ calls the C function _make_extobj, which may raise:
    # the resource is admitted with source enter faces, never as total.
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics.enter.completion, SourceEnterFacesCompletionV1)
    assert isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
    source_file = _open(root, "e.py", session=session)
    sugar = next(n.sugar() for n in source_file.nodes() if isinstance(n, With))
    assert type(sugar) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    completed = [face for face in exits if isinstance(face, Completed)]
    assert completed
    for face in completed:
        returns = [
            statement
            for statement in face.value.record.statements
            if isinstance(statement, ReturnValue)
        ]
        assert len(returns) == 1
        assert isinstance(returns[0].value, TermValue)
        assert returns[0].value.value == 1
    halted = [face for face in exits if isinstance(face, Halted)]
    assert halted
    assert all(isinstance(face.effect, UndeterminedRaiseEffect) for face in halted)
    assert any("_make_extobj" in face.effect.producer_node_owner for face in halted)


def test_enrolled_errstate_does_not_suppress_a_body_raise(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": ERRSTATE_RAISE})
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
    )
    ref = _with_resolution(root, "e.py", session=session)
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics.enter.completion, SourceEnterFacesCompletionV1)
    assert isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
    source_file = _open(root, "e.py", session=session)
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    raised = [
        face
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
    ]
    assert raised
    assert all(face.effect.exception_name == "RuntimeError" for face in raised)
    native = [
        face
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    ]
    assert native
    # The only completed face is the With's fact record: nothing returns and
    # nothing falls through, so no face completes past the raise.
    for face in exits:
        if isinstance(face, Completed):
            assert not face.value.record.can_fall_through
            assert not any(
                isinstance(statement, ReturnValue)
                for statement in face.value.record.statements
            )
