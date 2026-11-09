"""Authority twins for the authenticated-artifact-graph memo.

The law: **an authenticated artifact graph must be invalidated when the bytes it
authenticates change.** A CID that does not address its bytes is not a weak
cache, it is a violation of content addressing itself -- ``h = h(p)`` with the
``p`` swapped out from under it.

``_AUTHENTICATE_GRAPH_CACHE`` was keyed by dist-info PATH, and its disk twin was
keyed by a digest over ``RECORD``'s ``(mtime, size)`` -- which does not move when
an installed ``.py`` file is edited. Both served a graph reporting an artifact
CID for content that no longer existed on disk.

The repair is not a better invalidation check. It is the key: the memo is now
keyed by the ``distribution_artifact_cid``, which is a pure function of exactly
the bytes the graph authenticates. Stale is not detected, it is
UNREPRESENTABLE -- a changed byte changes the key, and a changed key is a miss.
That is also why this registry may be process-global where #6266's projection
memos could not be: the key is the complete key, and the value is frozen
content, not a node bound to somebody's live construction context.

The disk twin is gone. Every authentication reads the recorded bytes and
constructs the graph from them before any memo is consulted, so a disk seat
could only hand the same bytes back to be constructed again: a fresh process
parsed every recorded module twice, and a seat holding other bytes under an
authentic content CID was served. Twin 5 pins both.

Every twin carries a bite: a discrimination arm that reproduces the OLD
path-keyed shape and shows it answering wrongly on the same input, so no
positive assertion can pass vacuously.
"""

from __future__ import annotations

import csv
import dataclasses
import importlib.metadata
import os
import pickle
import sys
from pathlib import Path

import pytest

from sugar_lift_python_source import dependency_artifact as da
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph

_INIT = "from example_pkg.implementation import build\n"
_IMPL_A = "def build(value):\n    return value\n"
_IMPL_B = "def build(value):\n    return value + 1\n"


def _install(root: Path, *, implementation_source: str, dist: str = "example_dist"):
    """Install one authenticated distribution seat under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    package = root / "example_pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text(_INIT, encoding="utf-8")
    (package / "implementation.py").write_text(implementation_source, encoding="utf-8")
    metadata = root / f"{dist}-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist.replace('_', '-')}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("example_pkg\n", encoding="utf-8")
    recorded = (
        "example_pkg/__init__.py",
        "example_pkg/implementation.py",
        f"{dist}-1.0.dist-info/METADATA",
        f"{dist}-1.0.dist-info/top_level.txt",
        f"{dist}-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    sys.modules.pop("example_pkg", None)
    sys.modules.pop("example_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def _mutate(root: Path, implementation_source: str) -> None:
    """Mutate the INSTALLATION, exactly as `pip install -e` editing would.

    ``RECORD`` is deliberately left untouched: that is the point. An edited
    installed module does not restat the dist-info, which is why a RECORD-stat
    key cannot see this and a content key cannot miss it.
    """
    (root / "example_pkg" / "implementation.py").write_text(
        implementation_source, encoding="utf-8"
    )


def _on_disk(root: Path) -> str:
    return (root / "example_pkg" / "implementation.py").read_text(encoding="utf-8")


def _observable(graph: DependencyArtifactGraph) -> dict:
    """Everything an authentication answer says, flattened for comparison."""
    return {
        "artifact_kind": graph.artifact_kind,
        "distribution_name": graph.distribution_name,
        "distribution_version": graph.distribution_version,
        "distribution_artifact_cid": graph.distribution_artifact_cid,
        "files": [(item.source_seat, item.content_cid) for item in graph.files],
        "contents": [item.content for item in graph.files],
        "modules": {
            name: (module.source_seat, module.source_cid, module.source)
            for name, module in graph.modules.items()
        },
    }


# -- the defect, reproduced as a bite -----------------------------------------


class _PathKeyedMemo:
    """The OLD shape: one graph per dist-info path, checking nothing.

    Kept as an executable bite rather than prose. Every twin below runs its
    input through this too, and asserts the two shapes DISAGREE -- so a twin
    that stopped discriminating fails loudly instead of passing vacuously.
    """

    def __init__(self) -> None:
        self._by_path: dict[str, DependencyArtifactGraph] = {}

    def authenticate(
        self, distribution: importlib.metadata.Distribution
    ) -> DependencyArtifactGraph:
        key = str(Path(distribution._path).resolve())
        hit = self._by_path.get(key)
        if hit is not None:
            return hit
        graph = _uncached(distribution)
        self._by_path[key] = graph
        return graph


def _uncached(
    distribution: importlib.metadata.Distribution,
) -> DependencyArtifactGraph:
    """Authenticate paying full price, with every memo out of the way."""
    enabled = da._AUTHENTICATE_CACHE_ENABLED
    da._AUTHENTICATE_CACHE_ENABLED = False
    try:
        return DependencyArtifactGraph.authenticate(distribution)
    finally:
        da._AUTHENTICATE_CACHE_ENABLED = enabled


@pytest.fixture(autouse=True)
def _isolated_memos(tmp_path, monkeypatch):
    """Give each twin its own cache home and a cold in-memory table.

    Not a scrub of shared authority -- the in-memory table is content-addressed
    and could legitimately survive. It is isolation of the MEASUREMENT: a twin
    about cold-vs-warm cannot be read if a previous twin warmed it. The cache
    home is the twin's own so that "nothing is written there" and "nothing
    parked there answers" are both checkable.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(da, "_AUTHENTICATE_GRAPH_CACHE", {})
    monkeypatch.setattr(da, "_AUTHENTICATE_CACHE_ENABLED", True)
    monkeypatch.setattr(da, "_PACKAGES_DISTRIBUTIONS_CACHE", None)
    monkeypatch.setattr(da, "_TOP_LEVEL_GRAPH_CACHE", {})
    yield


# -- twin 1: mutation invalidates ---------------------------------------------


def test_mutating_the_installation_invalidates_the_cached_graph(tmp_path):
    """The reproduction, promoted to a permanent test."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)

    first = DependencyArtifactGraph.authenticate(distribution)
    assert first.modules["example_pkg.implementation"].source == _IMPL_A

    _mutate(root, _IMPL_B)
    second = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )

    assert second.modules["example_pkg.implementation"].source == _IMPL_B
    assert second.distribution_artifact_cid != first.distribution_artifact_cid


def test_equal_stat_metadata_cannot_hide_changed_installation_bytes(tmp_path):
    """A stat-identical mutation must not satisfy content authentication."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_B)
    implementation_path = root / "example_pkg" / "implementation.py"
    fixed_mtime_ns = 1_700_000_000_000_000_000
    os.utime(implementation_path, ns=(fixed_mtime_ns, fixed_mtime_ns))

    first = DependencyArtifactGraph.authenticate(distribution)

    replacement = "def build(value):\n    return value + 2\n"
    assert len(replacement) == len(_IMPL_B)
    _mutate(root, replacement)
    os.utime(implementation_path, ns=(fixed_mtime_ns, fixed_mtime_ns))
    second = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )
    truth = _uncached(importlib.metadata.Distribution.at(distribution._path))

    assert second.distribution_artifact_cid == truth.distribution_artifact_cid
    assert second.distribution_artifact_cid != first.distribution_artifact_cid
    assert second.modules["example_pkg.implementation"].source == replacement


def test_bite_the_path_keyed_memo_serves_the_stale_graph(tmp_path):
    """Bite for twin 1: same perturbation, old shape, wrong answer."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    memo = _PathKeyedMemo()

    first = memo.authenticate(distribution)
    _mutate(root, _IMPL_B)
    second = memo.authenticate(importlib.metadata.Distribution.at(distribution._path))

    # The defect, stated as an assertion so its removal is what fails.
    assert second is first
    assert second.modules["example_pkg.implementation"].source == _IMPL_A
    assert _on_disk(root) == _IMPL_B


# -- twin 2: the reported CID always addresses the bytes on disk ---------------


@pytest.mark.parametrize(
    "sequence",
    [
        (_IMPL_A,),
        (_IMPL_A, _IMPL_B),
        (_IMPL_A, _IMPL_B, _IMPL_A),
        (_IMPL_A, _IMPL_A),
        (_IMPL_B, "def build(value):\n    return value + 2\n", _IMPL_A),
    ],
)
def test_reported_artifact_cid_always_matches_the_bytes_on_disk(tmp_path, sequence):
    """h = h(p) is checked against a FRESH read, never against the memo."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=sequence[0])

    for implementation_source in sequence:
        _mutate(root, implementation_source)
        graph = DependencyArtifactGraph.authenticate(
            importlib.metadata.Distribution.at(distribution._path)
        )
        truth = _uncached(importlib.metadata.Distribution.at(distribution._path))
        assert graph.distribution_artifact_cid == truth.distribution_artifact_cid
        module = graph.modules["example_pkg.implementation"]
        assert module.source == _on_disk(root)
        recorded = {item.source_seat: item.content for item in graph.files}
        assert recorded["example_pkg/implementation.py"] == _on_disk(root).encode()


def test_bite_the_path_keyed_memo_reports_a_cid_that_addresses_nothing(tmp_path):
    """Bite for twin 2: the served CID names bytes that are not on disk."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    memo = _PathKeyedMemo()
    memo.authenticate(distribution)

    _mutate(root, _IMPL_B)
    stale = memo.authenticate(importlib.metadata.Distribution.at(distribution._path))
    truth = _uncached(importlib.metadata.Distribution.at(distribution._path))

    assert stale.distribution_artifact_cid != truth.distribution_artifact_cid
    assert stale.modules["example_pkg.implementation"].source != _on_disk(root)


# -- twin 3: two installations do not alias -----------------------------------


def test_two_distinct_installations_at_different_paths_do_not_alias(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_graph = DependencyArtifactGraph.authenticate(
        _install(left, implementation_source=_IMPL_A)
    )
    right_graph = DependencyArtifactGraph.authenticate(
        _install(right, implementation_source=_IMPL_B)
    )

    assert left_graph.distribution_artifact_cid != right_graph.distribution_artifact_cid
    assert left_graph.modules["example_pkg.implementation"].source == _IMPL_A
    assert right_graph.modules["example_pkg.implementation"].source == _IMPL_B
    assert left_graph.modules["example_pkg.implementation"].source == _on_disk(left)
    assert right_graph.modules["example_pkg.implementation"].source == _on_disk(right)


def test_identical_installations_at_different_paths_are_the_same_artifact(tmp_path):
    """The other face, and it is the LAW, not a leak.

    Two installations with byte-identical content ARE one artifact: the graph
    holds relative seats only, so there is no path inside it that could be
    wrong. Sharing here is ``h = h(p)`` doing its job. This twin exists so that
    a future agent reading twin 3 does not "fix" the aliasing question by
    putting the path back into the key -- the path is not part of the answer.
    """
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_graph = DependencyArtifactGraph.authenticate(
        _install(left, implementation_source=_IMPL_A)
    )
    right_graph = DependencyArtifactGraph.authenticate(
        _install(right, implementation_source=_IMPL_A)
    )

    assert left_graph.distribution_artifact_cid == right_graph.distribution_artifact_cid
    assert _observable(left_graph) == _observable(right_graph)
    assert all(
        not Path(item.source_seat).is_absolute() and "left" not in item.source_seat
        for item in left_graph.files
    )


def test_bite_distinct_installations_are_only_distinguished_by_content(tmp_path):
    """Bite for twin 3: the discriminator is CONTENT, and it moves both ways."""
    left = tmp_path / "left"
    right = tmp_path / "right"
    left_graph = DependencyArtifactGraph.authenticate(
        _install(left, implementation_source=_IMPL_A)
    )
    right_graph = DependencyArtifactGraph.authenticate(
        _install(right, implementation_source=_IMPL_B)
    )
    assert left_graph.distribution_artifact_cid != right_graph.distribution_artifact_cid

    # Converge the content; the artifacts must converge with it.
    _mutate(right, _IMPL_A)
    converged = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(right / "example_dist-1.0.dist-info")
    )
    assert converged.distribution_artifact_cid == left_graph.distribution_artifact_cid


# -- twin 4: the cheap path still works ---------------------------------------


def test_unchanged_installation_reauthenticates_to_an_identical_graph(tmp_path):
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)

    first = DependencyArtifactGraph.authenticate(distribution)
    second = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )

    # Not merely equal: the memo answered, which is what makes it a cache.
    assert second is first
    assert _observable(second) == _observable(first)


def test_bite_the_cheap_path_is_a_memo_and_not_a_rebuild(tmp_path):
    """Bite for twin 4: with the memo off, the same call rebuilds."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    first = DependencyArtifactGraph.authenticate(distribution)

    rebuilt = _uncached(importlib.metadata.Distribution.at(distribution._path))

    assert rebuilt is not first
    assert _observable(rebuilt) == _observable(first)


# -- twin 5: disablement changes speed only -----------------------------------


@pytest.mark.parametrize("implementation_source", [_IMPL_A, _IMPL_B])
def test_cache_disablement_changes_performance_only(tmp_path, implementation_source):
    """Never a CID, never a verdict, never a graph."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=implementation_source)

    warm = DependencyArtifactGraph.authenticate(distribution)
    warm_again = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )
    disabled = _uncached(importlib.metadata.Distribution.at(distribution._path))

    assert _observable(warm) == _observable(disabled)
    assert _observable(warm_again) == _observable(disabled)
    assert warm.distribution_artifact_cid == disabled.distribution_artifact_cid
    assert warm is warm_again and warm is not disabled


def test_cache_disablement_never_writes_a_memo_that_answers_later(tmp_path):
    """Disabled means disabled: no seat minted, in memory or on disk."""
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)

    _uncached(distribution)

    assert da._AUTHENTICATE_GRAPH_CACHE == {}
    assert not (tmp_path / "xdg").exists()


def _old_disk_seat(tmp_path: Path, artifact_cid: str) -> Path:
    """Where the deleted disk twin kept the graph for ``artifact_cid``."""
    digest = artifact_cid.removeprefix("blake3-512:")[:32]
    return tmp_path / "xdg" / "sugar" / "dependency-artifact-graphs" / f"{digest}.pkl"


def test_a_cold_process_table_parses_each_recorded_module_once(tmp_path, monkeypatch):
    """Truthful: one authentication costs one construction, and no disk seat.

    The disk twin made the second process pay twice: construct from the bytes
    just read, then load the seat and construct the same bytes again.
    """
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    warm = DependencyArtifactGraph.authenticate(distribution)

    parsed: list[str] = []
    real_gate = da._require_parseable_module_source

    def counted_gate(source, *, path, module_name):
        parsed.append(module_name)
        return real_gate(source, path=path, module_name=module_name)

    monkeypatch.setattr(da, "_require_parseable_module_source", counted_gate)
    # A new process: every process-local table is empty.
    da._AUTHENTICATE_GRAPH_CACHE.clear()
    da._TOP_LEVEL_GRAPH_CACHE.clear()
    cold = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )

    # Authentication parses nothing: a module is parsed when it is read.
    assert parsed == []
    first_read = _observable(cold)
    assert _observable(cold) == first_read
    # Every module was read twice and parsed once.
    assert sorted(parsed) == ["example_pkg", "example_pkg.implementation"]
    assert cold is not warm
    assert first_read == _observable(warm)
    assert not (tmp_path / "xdg").exists()


def test_bytes_parked_at_the_old_disk_seat_do_not_answer(tmp_path):
    """Lying: a seat holding other bytes under an authentic content CID.

    The disk twin re-derived the artifact CID from each row's recorded
    ``content_cid`` and never hashed the row's bytes, so this seat was served:
    the graph reported the installed artifact's CID and carried source that is
    not installed. Nothing reads the seat now.
    """
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    truth = _uncached(distribution)
    seat = _old_disk_seat(tmp_path, truth.distribution_artifact_cid)
    seat.parent.mkdir(parents=True)
    with seat.open("wb") as stream:
        pickle.dump(
            {
                "schema": "dep-graph-v4",
                "files": [
                    {
                        "source_seat": item.source_seat,
                        "content_cid": item.content_cid,
                        "content": (
                            _IMPL_B.encode()
                            if item.source_seat == "example_pkg/implementation.py"
                            else item.content
                        ),
                    }
                    for item in truth.files
                ],
            },
            stream,
            protocol=pickle.HIGHEST_PROTOCOL,
        )

    served = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )

    assert served.distribution_artifact_cid == truth.distribution_artifact_cid
    assert served.modules["example_pkg.implementation"].source == _on_disk(root)
    assert _on_disk(root) == _IMPL_A
    assert _observable(served) == _observable(truth)


# -- twin 6: the constructor owns graph fields --------------------------------


def test_graph_fields_cannot_directly_construct_an_incoherent_pair(tmp_path):
    """No caller, including the cache, may allocate a graph from derived fields."""
    distribution = _install(tmp_path / "project", implementation_source=_IMPL_A)
    graph = DependencyArtifactGraph.authenticate(distribution)

    with pytest.raises(da.DependencyArtifactAuthenticationError) as refused:
        DependencyArtifactGraph(
            artifact_kind="stdlib",
            distribution_name="pandas",
            distribution_version=graph.distribution_version,
            distribution_artifact_cid=graph.distribution_artifact_cid,
            files=graph.files,
            modules=graph.modules,
        )

    assert type(refused.value).__name__ == "DependencyArtifactConstructionError"


# -- twin 7: the value is not mutable, so a writer cannot leak -----------------


def test_a_served_graph_cannot_be_written_into(tmp_path):
    """The mutable-value question, answered as a test rather than a claim.

    #6266's deeper finding was that its memo VALUES were bound to a live
    mutable context. This one's are not: the graph is frozen, its files are
    frozen, and ``modules`` is a read-only proxy -- so there is no write a
    caller can perform that another authentication could observe.
    """
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    graph = DependencyArtifactGraph.authenticate(distribution)

    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.distribution_artifact_cid = "blake3-512:" + "0" * 128
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.files[0].content_cid = "blake3-512:" + "0" * 128
    with pytest.raises(TypeError):
        graph.modules["example_pkg.implementation"] = None
    assert not hasattr(graph.modules, "clear")
    assert not hasattr(graph.modules, "update")
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.modules["example_pkg.implementation"].source = _IMPL_B

    served = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )
    assert _observable(served) == _observable(graph)


def test_bite_a_forged_graph_cannot_be_minted_or_served(tmp_path):
    """Bite for twin 6: had the value been writable, THIS is what it would do.

    Constructing a graph whose CID does not address its files is refused at the
    one door, so the leak this twin guards against has no object to travel in.
    """
    root = tmp_path / "project"
    distribution = _install(root, implementation_source=_IMPL_A)
    graph = DependencyArtifactGraph.authenticate(distribution)

    with pytest.raises(da.DependencyArtifactAuthenticationError):
        DependencyArtifactGraph(
            artifact_kind=graph.artifact_kind,
            distribution_name=graph.distribution_name,
            distribution_version=graph.distribution_version,
            distribution_artifact_cid="blake3-512:" + "0" * 128,
            files=graph.files,
            modules=graph.modules,
        )
    with pytest.raises(da.DependencyArtifactAuthenticationError):
        DependencyArtifactGraph(
            artifact_kind=graph.artifact_kind,
            distribution_name=graph.distribution_name,
            distribution_version=graph.distribution_version,
            distribution_artifact_cid=graph.distribution_artifact_cid,
            files=graph.files,
            modules=graph.modules,
        )
