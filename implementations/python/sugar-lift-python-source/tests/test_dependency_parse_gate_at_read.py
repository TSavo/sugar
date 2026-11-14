"""A recorded module passes the parse gate when it is read, not before.

The gate ran over every recorded module while the graph was constructed: 1,463
compiles for pandas in every process, before the first question was asked. A
run over one file asks about a few dozen modules and paid for all of them.

Which bytes are installed is established by content address and does not
change here: the artifact CID, the file record and every module's seat, CID
and source are what they were. Only the moment of the gate moves, to the read
of the module it gates.

Twins:
  truthful -- authenticating compiles nothing; reading a module compiles that
              module once, and never again;
  lying    -- an unparseable recorded module is handed to no reader: every way
              of reading it is refused by name, every time, while the modules
              beside it are still served.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_python_source import dependency_artifact as da
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
)

GOOD = "def build(value):\n    return value\n"
OTHER = "LIMIT = 3\n"
UNPARSEABLE = "def build(:\n    pass\n"
REFUSAL = "recorded Python module gated_pkg.broken is not parseable UTF-8 source"


def _distribution(root: Path, *, name: str, seats: dict[str, str]):
    """Record exactly ``seats`` (seat -> source) as one installed distribution."""
    for seat, source in seats.items():
        path = root / seat
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    metadata = root / f"{name}-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8"
    )
    recorded = [
        *sorted(seats),
        f"{name}-1.0.dist-info/METADATA",
        f"{name}-1.0.dist-info/RECORD",
    ]
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in recorded:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


@pytest.fixture
def gate_calls(monkeypatch):
    """Every module the parse gate is asked about, in order."""
    calls: list[str] = []
    real_gate = da._require_parseable_module_source

    def counted(source, *, path, module_name):
        calls.append(module_name)
        return real_gate(source, path=path, module_name=module_name)

    monkeypatch.setattr(da, "_require_parseable_module_source", counted)
    monkeypatch.setattr(da, "_AUTHENTICATE_CACHE_ENABLED", False)
    return calls


def _parseable(tmp_path: Path):
    return _distribution(
        tmp_path,
        name="gated_dist",
        seats={
            "gated_pkg/__init__.py": OTHER,
            "gated_pkg/first.py": GOOD,
            "gated_pkg/second.py": GOOD,
            "gated_pkg/third.py": OTHER,
        },
    )


def _with_one_unparseable(tmp_path: Path):
    return _distribution(
        tmp_path,
        name="gated_dist",
        seats={
            "gated_pkg/__init__.py": OTHER,
            "gated_pkg/broken.py": UNPARSEABLE,
            "gated_pkg/whole.py": GOOD,
        },
    )


# -- truthful ------------------------------------------------------------------


def test_authenticating_a_distribution_parses_no_module(
    tmp_path: Path, gate_calls
) -> None:
    graph = DependencyArtifactGraph.authenticate(_parseable(tmp_path))

    assert gate_calls == []
    # Names and length need no source, so they run no gate either.
    assert sorted(graph.modules) == [
        "gated_pkg",
        "gated_pkg.first",
        "gated_pkg.second",
        "gated_pkg.third",
    ]
    assert len(graph.modules) == 4
    assert sorted(graph.modules.keys()) == sorted(graph.modules)
    assert gate_calls == []


def test_reading_a_module_parses_that_module_once(tmp_path: Path, gate_calls) -> None:
    graph = DependencyArtifactGraph.authenticate(_parseable(tmp_path))

    first = graph.modules["gated_pkg.first"]
    assert gate_calls == ["gated_pkg.first"]
    assert first.source == GOOD
    assert first.source_seat == "gated_pkg/first.py"
    assert first.source_cid == da.blake3_512_of(GOOD.encode("utf-8"))

    # Every later read, by any door, is answered without the gate.
    assert graph.modules["gated_pkg.first"] is first
    assert graph.modules.get("gated_pkg.first") is first
    assert "gated_pkg.first" in graph.modules
    assert gate_calls == ["gated_pkg.first"]

    # A module that is not recorded is absent, and asks the gate nothing.
    assert "gated_pkg.missing" not in graph.modules
    assert graph.modules.get("gated_pkg.missing") is None
    with pytest.raises(KeyError):
        graph.modules["gated_pkg.missing"]
    assert gate_calls == ["gated_pkg.first"]

    # Reading all of them parses the rest, each once.
    assert dict(graph.modules.items()) == dict(graph.modules.items())
    assert sorted(gate_calls) == [
        "gated_pkg",
        "gated_pkg.first",
        "gated_pkg.second",
        "gated_pkg.third",
    ]


def test_the_authentication_answer_is_what_the_eager_gate_gave(
    tmp_path: Path, gate_calls
) -> None:
    """The gate's moment moved; no CID, seat or source did."""
    graph = DependencyArtifactGraph.authenticate(_parseable(tmp_path))
    expected_files = {
        "gated_pkg/__init__.py": OTHER,
        "gated_pkg/first.py": GOOD,
        "gated_pkg/second.py": GOOD,
        "gated_pkg/third.py": OTHER,
    }
    module_files = [
        item for item in graph.files if item.source_seat.startswith("gated_pkg/")
    ]
    assert {item.source_seat: item.content for item in module_files} == {
        seat: source.encode("utf-8") for seat, source in expected_files.items()
    }
    assert graph.distribution_artifact_cid == da.cid_of_json(
        {
            "kind": "python-dependency-artifact",
            "schemaVersion": "1",
            "distributionName": "gated_dist",
            "distributionVersion": "1.0",
            "files": [
                {"path": item.source_seat, "contentCid": item.content_cid}
                for item in graph.files
            ],
        }
    )
    assert {
        name: (module.source_seat, module.source_cid, module.source)
        for name, module in graph.modules.items()
    } == {
        "gated_pkg": (
            "gated_pkg/__init__.py",
            da.blake3_512_of(OTHER.encode("utf-8")),
            OTHER,
        ),
        "gated_pkg.first": (
            "gated_pkg/first.py",
            da.blake3_512_of(GOOD.encode("utf-8")),
            GOOD,
        ),
        "gated_pkg.second": (
            "gated_pkg/second.py",
            da.blake3_512_of(GOOD.encode("utf-8")),
            GOOD,
        ),
        "gated_pkg.third": (
            "gated_pkg/third.py",
            da.blake3_512_of(OTHER.encode("utf-8")),
            OTHER,
        ),
    }


def test_the_module_map_cannot_be_written(tmp_path: Path) -> None:
    graph = DependencyArtifactGraph.authenticate(_parseable(tmp_path))
    served = graph.modules["gated_pkg.first"]

    with pytest.raises(TypeError):
        graph.modules["gated_pkg.first"] = served  # type: ignore[index]
    with pytest.raises(TypeError):
        del graph.modules["gated_pkg.first"]  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        graph.modules.invented = served  # type: ignore[attr-defined]
    for method in ("pop", "update", "clear", "setdefault", "popitem"):
        assert not hasattr(graph.modules, method)


# -- lying ---------------------------------------------------------------------


def test_an_unparseable_module_is_refused_by_name_at_every_read(
    tmp_path: Path, gate_calls
) -> None:
    graph = DependencyArtifactGraph.authenticate(_with_one_unparseable(tmp_path))
    # It is recorded, and its bytes are authenticated like any other file.
    assert "gated_pkg.broken" in list(graph.modules)
    assert gate_calls == []

    def by_index():
        return graph.modules["gated_pkg.broken"]

    def by_get():
        return graph.modules.get("gated_pkg.broken")

    def by_get_with_default():
        return graph.modules.get("gated_pkg.broken", None)

    def by_membership():
        return "gated_pkg.broken" in graph.modules

    def by_items():
        return list(graph.modules.items())

    def by_values():
        return list(graph.modules.values())

    def by_equality():
        return graph.modules == {}

    doors = (
        by_index,
        by_get,
        by_get_with_default,
        by_membership,
        by_items,
        by_values,
        by_equality,
    )
    for door in doors:
        with pytest.raises(DependencyArtifactAuthenticationError) as refused:
            door()
        assert str(refused.value) == REFUSAL
        assert isinstance(refused.value.__cause__, SyntaxError)

    # Refused every time: a failed gate admits nothing, so it is asked again.
    assert gate_calls.count("gated_pkg.broken") == len(doors)
    with pytest.raises(DependencyArtifactAuthenticationError, match=REFUSAL):
        by_index()


def test_modules_beside_an_unparseable_one_are_still_served(
    tmp_path: Path, gate_calls
) -> None:
    graph = DependencyArtifactGraph.authenticate(_with_one_unparseable(tmp_path))

    whole = graph.modules["gated_pkg.whole"]
    assert whole.source == GOOD
    assert graph.modules["gated_pkg"].source == OTHER
    assert gate_calls == ["gated_pkg.whole", "gated_pkg"]

    with pytest.raises(DependencyArtifactAuthenticationError, match=REFUSAL):
        graph.modules["gated_pkg.broken"]
    # The refusal did not unseat what was already admitted.
    assert graph.modules["gated_pkg.whole"] is whole
    assert gate_calls == ["gated_pkg.whole", "gated_pkg", "gated_pkg.broken"]


def test_a_module_that_is_not_utf8_is_still_refused_at_authentication(
    tmp_path: Path,
) -> None:
    """Decoding is not the parse gate: bytes that are not text seat no module."""
    distribution = _with_one_unparseable(tmp_path)
    (tmp_path / "gated_pkg" / "whole.py").write_bytes(b"NAME = '\xff\xfe'\n")

    with pytest.raises(DependencyArtifactAuthenticationError) as refused:
        DependencyArtifactGraph.authenticate(distribution)
    assert str(refused.value) == (
        "recorded Python module gated_pkg.whole is not parseable UTF-8 source"
    )
