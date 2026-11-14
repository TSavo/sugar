"""The population follows from what the code imports, never from a list.

Board 33982802518: cmResolutions constructed 0 / cited-opaque 5,812 /
unconstructed 2,245, because stdlib was refused by KIND and every
non-corpus distribution by absence from a one-name roster. The population
is the corpus distribution plus every top-level module the code imports,
read from the one import table (#7837, #7851). No package name is listed in
code; ``SUGAR_ENROLLED_POPULATIONS`` may still declare more, optionally one
module at a time (``cpython-stdlib:contextlib``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_python_source import resolution_session
from sugar_lift_python_source.resolution_session import (
    ENROLLED_POPULATIONS_ENV,
    SourceResolutionSession,
    clear_walk_sessions,
    declared_extra_populations,
    enrolled_population_roster,
    population_admits,
)
from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
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
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter


def test_no_package_name_is_listed_in_code(monkeypatch) -> None:
    """Nothing is enrolled by a hard-coded name: with nothing declared, the
    roster is the corpus distribution alone."""
    monkeypatch.delenv(ENROLLED_POPULATIONS_ENV, raising=False)
    assert not hasattr(resolution_session, "STANDING_EXTRA_POPULATIONS")
    assert declared_extra_populations() == frozenset()
    assert enrolled_population_roster("pandas") == frozenset({"pandas"})
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "pytest, cpython-stdlib:contextlib ,numpy")
    assert declared_extra_populations() == frozenset(
        {"pytest", "cpython-stdlib:contextlib", "numpy"}
    )
    assert "pandas" in enrolled_population_roster("pandas")


def test_an_import_admits_its_own_top_level_module_only() -> None:
    roster = frozenset({"tiny-corpus"})
    imported = frozenset({"contextlib", "numpy"})
    assert population_admits(roster, "cpython-stdlib", "contextlib", imported)
    assert population_admits(roster, "numpy", "numpy._core._ufunc_config", imported)
    assert not population_admits(roster, "cpython-stdlib", "warnings", imported)
    assert not population_admits(roster, "cpython-stdlib", "contextlib")
    # No module, no admission by import: an import never admits a module no
    # artifact authenticates.
    assert not population_admits(roster, "contextlib", None, imported)


def test_malformed_entries_refuse(monkeypatch) -> None:
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "cpython-stdlib:contextlib.nullcontext")
    with pytest.raises(TypeError, match="not a distribution name"):
        declared_extra_populations()
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "pytest raises")
    with pytest.raises(TypeError):
        declared_extra_populations()


def test_module_scoped_entry_admits_only_its_module() -> None:
    roster = frozenset({"pandas", "cpython-stdlib:contextlib"})
    assert population_admits(roster, "pandas", "pandas.core.frame")
    assert population_admits(roster, "cpython-stdlib", "contextlib")
    assert not population_admits(roster, "cpython-stdlib", "warnings")
    assert not population_admits(roster, "cpython-stdlib", None)
    assert population_admits(frozenset({"cpython-stdlib"}), "cpython-stdlib", "warnings")
    assert not population_admits(roster, "pytest", "_pytest.raises")


NULLCONTEXT = (
    "from contextlib import nullcontext\n"
    "\n"
    "def f():\n"
    "    with nullcontext():\n"
    "        return 1\n"
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


def _open(root: Path, name: str, *, session=None):
    clear_walk_sessions()
    kwargs = {
        "root": root,
        "reporter": CollectingReporter(),
        "distribution": "tiny-corpus",
        "source_workspace_root": root,
    }
    if session is not None:
        kwargs["resolution_session"] = session
    return open_source_file_for_construction(root / name, **kwargs)


def test_population_follows_from_imports_alone(tmp_path, monkeypatch) -> None:
    """A corpus-only roster, nothing declared, no distribution passed: the
    one thing that enrolls contextlib is that the code imports it.

    Before the open the session holds no imported module and contextlib is
    off-population; the open reads the one import table, so contextlib joins
    and ``nullcontext`` is derived from its source. ``warnings`` is not
    imported, so it stays off-population.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.canonicalizer import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_construction import (
        _graph_is_off_population,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_source_tree.tree import SourceFile

    monkeypatch.delenv(ENROLLED_POPULATIONS_ENV, raising=False)
    root = _corpus(tmp_path, **{"nc.py": NULLCONTEXT})
    path = root / "nc.py"
    source = path.read_text(encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    assert tree.unit.imported_modules() == frozenset({"contextlib"})
    session = SourceResolutionSession(enrolled_distributions=frozenset({"tiny-corpus"}))
    stdlib = SimpleNamespace(distribution_name="cpython-stdlib")
    assert session.imported_modules == frozenset()
    assert _graph_is_off_population(stdlib, session=session, module_name="contextlib")
    populate_source_derived_resource_refs(tree, root=root, path=path, session=session)
    assert session.enrolled_distributions == frozenset({"tiny-corpus"})
    assert session.imported_modules == frozenset({"contextlib"})
    assert not _graph_is_off_population(stdlib, session=session, module_name="contextlib")
    assert _graph_is_off_population(stdlib, session=session, module_name="warnings")
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref


def test_importing_contextlib_stops_citing_nullcontext(tmp_path, monkeypatch) -> None:
    """Truthful twin: the code imports contextlib, so nullcontext is derived
    from its source as a protocol resource that never suppresses."""
    monkeypatch.delenv(ENROLLED_POPULATIONS_ENV, raising=False)
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
    root = _corpus(tmp_path, **{"nc.py": source})
    source_file = _open(root, "nc.py")
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
