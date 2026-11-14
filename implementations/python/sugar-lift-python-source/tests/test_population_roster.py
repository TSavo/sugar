"""The population is step 2's file list and nothing else.

Every ``sugar.enumerate`` level opens its file through the one opener, and the
opener populates under the walk session for the root (#7796). That session's
roster is ``project_file_roster(root)``: the content CID of every file step 2
lists. No distribution is enrolled by name, no module by a module-scoped
entry or a standing extra, and no module by being imported. A module is
enrolled only when the source its artifact seats for it is a listed file. An
imported call is a coordinate plus an edge answered by an imported proof; its
body is never lifted, so an installed module outside the list is cited.
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
from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
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


def test_only_a_listed_file_enrolls_a_module() -> None:
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({"blake3-512:listed"})
    )
    listed = _graph("blake3-512:listed", files=("blake3-512:listed",))
    other = _graph("blake3-512:other", files=("blake3-512:other",))
    assert not _graph_is_off_population(listed, session=session, module_name="m")
    assert _graph_is_off_population(other, session=session, module_name="m")
    assert not _graph_is_off_population(listed, session=session)
    assert _graph_is_off_population(other, session=session)
    # Nothing else admits: not a module the artifact holds no source for, not
    # a module no artifact authenticates.
    assert _graph_is_off_population(_graph(None), session=session, module_name="m")
    assert _graph_is_off_population(None, session=session, module_name="m")


def test_the_session_has_no_import_admission() -> None:
    """An import is an edge, not population: the session carries no second
    roster of imported modules beside the file list (#7796)."""
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    assert not hasattr(session, "imported_modules")


def test_importing_contextlib_leaves_nullcontext_cited(tmp_path) -> None:
    """contextlib is installed, not one of step 2's files. Importing it does
    not enroll it: nullcontext is an imported call, cited, never lifted."""
    source = (
        "from contextlib import nullcontext\n"
        "\n"
        "def complete_body():\n"
        "    with nullcontext():\n"
        "        return 1\n"
    )
    root = _project(tmp_path, **{"nc.py": source})
    source_file = open_source_file_for_construction(
        root / "nc.py", root=root, reporter=CollectingReporter()
    )
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    assert len(refs) == 1
    for ref in refs.values():
        assert not isinstance(ref, SourceDerivedContextManagerRefV1), ref
        assert isinstance(ref, OpaqueCitedContextManagerRefV1), ref
