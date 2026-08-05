"""The terminal export memo must carry its own re-export hops.

``resolve_export`` shares one *terminal* memo keyed on
``(distribution_artifact_cid, module_name, exported_name)``.  The value it
stores is the resolution of that symbol: a module/source/definition triple that
may sit several re-export hops *below* the keyed module.

Those hops are part of the memo value, not part of the caller's path.  Storing
the triple while discarding them makes the memo answer a different question
than the uncached resolve:

* a hop restamps its own path warrants onto a triple that no longer reaches
  from the keyed module to the definition -- ``ResolvedPythonObjectV1``
  refuses it as ``re-export warrants do not reach the resolved definition``,
  and the refusal escapes ``sugar.enumerate`` as an untyped instrument
  failure rather than a construction panic;
* a pure entry restamps ``()`` and silently publishes a definition in a module
  the queried module never names, with no warrant at all.

Both twins here are the *same* defect at the two doors that read the memo.
Each asserts the specific text / the specific chain, and each carries a
discrimination arm: the uncached resolve (memo disabled) is the oracle, so the
positive assertion cannot pass vacuously.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _dist(
    root: Path, *, name: str, files: dict[str, str], tops: tuple[str, ...]
) -> importlib.metadata.Distribution:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    meta = root / f"{name.replace('-', '_')}_dist-1.0.dist-info"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (meta / "top_level.txt").write_text(
        "".join(f"{top}\n" for top in tops), encoding="utf-8"
    )
    recorded = (
        *files.keys(),
        f"{meta.name}/METADATA",
        f"{meta.name}/top_level.txt",
        f"{meta.name}/RECORD",
    )
    with (meta / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(meta)


def _demand(root: Path, stem: str, source: str):
    path = root / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        root, path, source, blake3_512_of(source.encode("utf-8")), module_identities={}
    )
    assert len(receipts) == 1
    return receipts[0]


def _session(graph, *, enabled: bool = True) -> SourceResolutionSession:
    name = graph.distribution_name
    assert name, "fixture distribution must be named"
    return SourceResolutionSession(
        enabled=enabled, enrolled_distributions=frozenset({name})
    )


def _chain(resolved: ResolvedPythonObjectV1) -> list[tuple[str, str]]:
    """The hop path this resolution testifies to, from-module -> to-module."""
    return [(w.from_module, w.to_module) for w in resolved.reexport_warrants]


# ---------------------------------------------------------------- fixture


def _shared_middle_files(marker: str) -> dict[str, str]:
    """Two entry packages re-exporting one name through one shared middle.

    ``marker`` keeps each test's module bytes unique: SourceUnits are memoized
    by (source_cid, workspace-relative filename), so byte-identical fixtures in
    two tests would share one unit and hide a per-test difference (#7364).
    """
    return {
        "shared_pkg/__init__.py": f"# entry {marker}\nfrom mid_pkg import build\n",
        "other_pkg/__init__.py": f"# other entry {marker}\nfrom mid_pkg import build\n",
        "mid_pkg/__init__.py": (
            f"# middle {marker}\nfrom mid_pkg.implementation import build\n"
        ),
        "mid_pkg/implementation.py": (
            f"# implementation {marker}\ndef build(value):\n    return value\n"
        ),
    }


_TOPS = ("shared_pkg", "other_pkg", "mid_pkg")
_HOPS = [("shared_pkg", "mid_pkg"), ("mid_pkg", "mid_pkg.implementation")]
_OTHER_HOPS = [("other_pkg", "mid_pkg"), ("mid_pkg", "mid_pkg.implementation")]
_MIDDLE_HOPS = [("mid_pkg", "mid_pkg.implementation")]


# ------------------------------------------------------- twin 1: the hop


def test_second_path_through_a_shared_middle_reaches_the_definition(
    tmp_path: Path,
) -> None:
    """A hop that hits the terminal memo still testifies to a whole chain.

    ``shared_pkg`` and ``other_pkg`` both re-export ``build`` through
    ``mid_pkg``.  Resolving the first fills the terminal memo for
    ``mid_pkg``; the second arrives at that key with its own path
    warrant and must compose, not refuse.
    """
    graph = DependencyArtifactGraph.authenticate(
        _dist(tmp_path, name="shared-pkg", files=_shared_middle_files("twin-one"), tops=_TOPS)
    )
    session = _session(graph)

    first = resolve_import_binding(
        _demand(tmp_path, "consumer_a", "import shared_pkg\nshared_pkg.build(1)\n"),
        graph=graph,
        session=session,
    )
    assert isinstance(first, ResolvedPythonObjectV1), first
    assert _chain(first) == _HOPS

    second = resolve_import_binding(
        _demand(
            tmp_path,
            "consumer_b",
            "import other_pkg\nother_pkg.build(2)\n",
        ),
        graph=graph,
        session=session,
    )
    assert isinstance(second, ResolvedPythonObjectV1), second
    assert second.module_name == "mid_pkg.implementation"
    assert _chain(second) == _OTHER_HOPS
    assert second.reexport_warrants[-1].to_module == second.module_name


def test_hop_after_shared_middle_matches_the_uncached_resolve(tmp_path: Path) -> None:
    """Discrimination arm for twin 1: the memo may change speed only.

    Without the memo no terminal is ever consulted, so this run is the oracle.
    If twin 1 passed only because the memo were disabled, this arm would still
    pass while twin 1 failed -- they are asserted to agree.
    """
    graph = DependencyArtifactGraph.authenticate(
        _dist(tmp_path, name="shared-pkg", files=_shared_middle_files("twin-one-arm"), tops=_TOPS)
    )
    cold = _session(graph, enabled=False)

    resolve_import_binding(
        _demand(tmp_path, "consumer_a", "import shared_pkg\nshared_pkg.build(1)\n"),
        graph=graph,
        session=cold,
    )
    second = resolve_import_binding(
        _demand(
            tmp_path,
            "consumer_b",
            "import other_pkg\nother_pkg.build(2)\n",
        ),
        graph=graph,
        session=cold,
    )
    assert isinstance(second, ResolvedPythonObjectV1), second
    assert _chain(second) == _OTHER_HOPS


# ------------------------------------------------ twin 2: the pure entry


def test_pure_entry_on_a_hop_filled_terminal_keeps_its_warrant(tmp_path: Path) -> None:
    """A pure entry that hits a hop-filled terminal must not lose the hop.

    ``mid_pkg`` is first reached as an intermediate hop, which fills the
    terminal memo (hops never write the pure-entry memo).  A later direct
    demand on ``mid_pkg.build`` reads that terminal.  The answer is a
    definition in ``mid_pkg.implementation`` -- a module ``mid_pkg`` only
    reaches through one re-export -- so the warrant for that hop must be
    present.  An empty chain here is a definition published with no provenance.
    """
    graph = DependencyArtifactGraph.authenticate(
        _dist(tmp_path, name="shared-pkg", files=_shared_middle_files("twin-two"), tops=_TOPS)
    )
    session = _session(graph)

    resolve_import_binding(
        _demand(tmp_path, "consumer_a", "import shared_pkg\nshared_pkg.build(1)\n"),
        graph=graph,
        session=session,
    )
    direct = resolve_import_binding(
        _demand(
            tmp_path,
            "consumer_c",
            "import mid_pkg\nmid_pkg.build(3)\n",
        ),
        graph=graph,
        session=session,
    )
    assert isinstance(direct, ResolvedPythonObjectV1), direct
    assert direct.module_name == "mid_pkg.implementation"
    assert _chain(direct) == _MIDDLE_HOPS


def test_pure_entry_after_hop_matches_the_uncached_resolve(tmp_path: Path) -> None:
    """Discrimination arm for twin 2: the uncached resolve is the oracle."""
    graph = DependencyArtifactGraph.authenticate(
        _dist(tmp_path, name="shared-pkg", files=_shared_middle_files("twin-two-arm"), tops=_TOPS)
    )
    cold = _session(graph, enabled=False)

    resolve_import_binding(
        _demand(tmp_path, "consumer_a", "import shared_pkg\nshared_pkg.build(1)\n"),
        graph=graph,
        session=cold,
    )
    direct = resolve_import_binding(
        _demand(
            tmp_path,
            "consumer_c",
            "import mid_pkg\nmid_pkg.build(3)\n",
        ),
        graph=graph,
        session=cold,
    )
    assert isinstance(direct, ResolvedPythonObjectV1), direct
    assert _chain(direct) == _MIDDLE_HOPS
