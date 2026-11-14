"""The roster is step 2's file list; the rest of the population follows imports.

Every ``sugar.enumerate`` level opens its file through the one opener, and the
opener populates under the walk session for the root (#7796). That session's
roster is ``project_file_roster(root)``: the content CID of every file step 2
lists. No distribution is enrolled by name and no module by a module-scoped
entry or a standing extra. A module is enrolled when the source its artifact
seats for it is a listed file, or when the opened code imports its top-level
module (``imported_modules``, read from the one import table; #7859, #7866).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sugar_lift_python_source import resolution_session
from sugar_lift_python_source.manager_construction import _graph_is_off_population
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
    project_file_roster,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete, Halted
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter

def setup_function() -> None:
    clear_walk_sessions()


def teardown_function() -> None:
    clear_walk_sessions()


def _project(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "p"
    root.mkdir()
    for name, source in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return root


def _graph(cid: str | None, *, files: tuple[str, ...] = ()):
    return SimpleNamespace(
        modules=SimpleNamespace(source_cid_of=lambda _name: cid),
        files=tuple(SimpleNamespace(content_cid=item) for item in files),
    )


def test_no_package_name_is_listed_in_code_or_the_environment() -> None:
    for name in (
        "STANDING_EXTRA_POPULATIONS",
        "ENROLLED_POPULATIONS_ENV",
        "declared_extra_populations",
        "enrolled_population_roster",
        "population_admits",
    ):
        assert not hasattr(resolution_session, name), name


def test_roster_is_the_content_cid_of_every_listed_file(tmp_path) -> None:
    root = _project(
        tmp_path,
        **{"a.py": "x = 1\n", "pkg/b.py": "y = 2\n", "pkg/__init__.py": ""},
    )
    (root / "notes.txt").write_text("not a source file\n", encoding="utf-8")
    expected = frozenset(
        path_source(str(root / name))[2]
        for name in ("a.py", "pkg/b.py", "pkg/__init__.py")
    )
    roster = project_file_roster(root)
    assert roster == expected
    for name in ("cpython-stdlib:contextlib", "numpy", "pytest", "cpython-stdlib"):
        assert name not in roster


def test_the_open_populates_under_the_file_roster(tmp_path, monkeypatch) -> None:
    """No level opens without populating, and none names a distribution."""
    from sugar_lift_python_source import manager_summary_derivation as msd

    root = _project(tmp_path, **{"a.py": "x = 1\n"})
    seen: list[object] = []
    original = msd.populate_source_derived_resource_refs

    def capture(source_file, *, root, path, session=None, **kwargs):
        seen.append(session)
        return original(source_file, root=root, path=path, session=session, **kwargs)

    monkeypatch.setattr(msd, "populate_source_derived_resource_refs", capture)
    open_source_file_for_construction(root / "a.py", root=root)
    assert len(seen) == 1
    assert seen[0].enrolled_distributions == project_file_roster(root)


def test_a_listed_file_or_an_import_enrolls_a_module() -> None:
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({"blake3-512:listed"})
    )
    listed = _graph("blake3-512:listed", files=("blake3-512:listed",))
    other = _graph("blake3-512:other", files=("blake3-512:other",))
    assert not _graph_is_off_population(listed, session=session, module_name="m")
    assert _graph_is_off_population(other, session=session, module_name="m")
    assert not _graph_is_off_population(listed, session=session)
    assert _graph_is_off_population(other, session=session)
    # The code imports ``m``: its artifact's module joins the population.
    session.imported_modules = frozenset({"m"})
    assert not _graph_is_off_population(other, session=session, module_name="m.sub")
    assert _graph_is_off_population(other, session=session, module_name="n")
    # An import never admits a module the artifact holds no source for, nor a
    # module no artifact authenticates.
    assert _graph_is_off_population(_graph(None), session=session, module_name="m")
    assert _graph_is_off_population(None, session=session, module_name="m")


def test_importing_contextlib_stops_citing_nullcontext(tmp_path) -> None:
    """Truthful twin: the code imports contextlib, so nullcontext is derived
    from its source as a protocol resource that never suppresses."""
    source = (
        "from contextlib import nullcontext\n"
        "\n"
        "def complete_body():\n"
        "    with nullcontext():\n"
        "        return 1\n"
        "\n"
        "def raising_body():\n"
        "    with nullcontext():\n"
        "        raise ValueError('boom')\n"
    )
    root = _project(tmp_path, **{"nc.py": source})
    source_file = open_source_file_for_construction(
        root / "nc.py", root=root, reporter=CollectingReporter()
    )
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    assert len(refs) == 2
    for ref in refs.values():
        assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
        assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
        assert not isinstance(ref.semantics, EffectBoundarySemanticsV1)
        assert isinstance(ref.semantics.exit.disposition, NeverSuppressesDispositionV1)
    for node in source_file.nodes():
        if isinstance(node, With):
            sugar = node.sugar()
            assert isinstance(sugar, WithSourceResourceSugar)
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
