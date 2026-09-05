"""Plan Cut 1: the population membrane is roster-only, declared, module-scoped.

Board 33982802518: cmResolutions constructed 0 / cited-opaque 5,812 /
unconstructed 2,245, because stdlib was refused by KIND and every
non-corpus distribution by absence from a one-name roster. The population
is now what the measurement DECLARES (``SUGAR_ENROLLED_POPULATIONS``):
the corpus distribution plus extra authenticated source populations,
optionally one module at a time (``cpython-stdlib:contextlib``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_python_source.resolution_session import (
    ENROLLED_POPULATIONS_ENV,
    clear_walk_sessions,
    declared_extra_populations,
    enrolled_population_roster,
    population_admits,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    OpaqueCitedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.nodes import With
from sugar_source_tree.reporter import CollectingReporter


def test_roster_is_the_corpus_plus_declared_extras(monkeypatch) -> None:
    monkeypatch.delenv(ENROLLED_POPULATIONS_ENV, raising=False)
    assert enrolled_population_roster("pandas") == frozenset({"pandas"})
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "pytest, cpython-stdlib:contextlib ,numpy")
    assert declared_extra_populations() == frozenset(
        {"pytest", "cpython-stdlib:contextlib", "numpy"}
    )
    assert "pandas" in enrolled_population_roster("pandas")


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
WARNINGS = (
    "import warnings\n"
    "\n"
    "def f():\n"
    "    with warnings.catch_warnings():\n"
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


def _with_resolution(root: Path, name: str):
    clear_walk_sessions()
    source_file = open_source_file_for_construction(
        root / name,
        root=root,
        reporter=CollectingReporter(),
        distribution="tiny-corpus",
        source_workspace_root=root,
    )
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    return refs[site]


def test_stdlib_manager_is_cited_under_the_corpus_only_roster(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(ENROLLED_POPULATIONS_ENV, raising=False)
    root = _corpus(tmp_path, **{"nc.py": NULLCONTEXT})
    ref = _with_resolution(root, "nc.py")
    assert isinstance(ref, OpaqueCitedContextManagerRefV1)
    assert ref.roster.resolution_kind == "call-target-off-population"


def test_enrolling_contextlib_stops_citing_nullcontext(tmp_path, monkeypatch) -> None:
    """Truthful twin: with contextlib enrolled the membrane no longer cites;
    whatever derivation says next is a NAMED fact about nullcontext's body,
    never an off-population citation."""
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "cpython-stdlib:contextlib")
    root = _corpus(tmp_path, **{"nc.py": NULLCONTEXT})
    ref = _with_resolution(root, "nc.py")
    assert not isinstance(ref, OpaqueCitedContextManagerRefV1), ref
    if isinstance(ref, ContextManagerResolutionGapV1):
        assert ref.kind != "call-target-off-population", ref
        print("nullcontext derivation gap:", ref.kind, ref.detail)
    else:
        print("nullcontext derived:", type(ref).__name__)


def test_enrolling_contextlib_does_not_enroll_warnings(tmp_path, monkeypatch) -> None:
    """Lying twin: a module-scoped entry admits one module, not the stdlib."""
    monkeypatch.setenv(ENROLLED_POPULATIONS_ENV, "cpython-stdlib:contextlib")
    root = _corpus(tmp_path, **{"w.py": WARNINGS})
    ref = _with_resolution(root, "w.py")
    assert isinstance(ref, OpaqueCitedContextManagerRefV1)
    assert ref.roster.resolution_kind == "call-target-off-population"
