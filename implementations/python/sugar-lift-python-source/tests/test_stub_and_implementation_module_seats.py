"""A ``.pyi`` stub beside its ``.py`` is one module seat, not two rivals.

numpy records 151 ``x.py``/``x.pyi`` pairs.  Reading the pair as a duplicate
module seat refused the ENTIRE numpy dependency graph at the first collision
(``numpy.__config__``), so every numpy manager in the enrolled corpus cited
``no-derived-contract`` while its defining source sat recorded and parseable in
the distribution.  PEP 484 is explicit that a stub declares the module its
implementation defines; it is not a second definition of that name.

The refusal itself is NOT relaxed.  Two seats that collide on a module name
without sharing a stem stay rivals and are still refused with the same text.
Each tooth below asserts the SPECIFIC refusal or the SPECIFIC seated
implementation, so a neighbouring refusal cannot satisfy it.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
)

IMPLEMENTATION = "IMPLEMENTATION_MARKER = 1\n"
STUB = "STUB_MARKER: int\n"


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


def test_stub_beside_implementation_seats_the_implementation(tmp_path: Path) -> None:
    """The numpy shape: both seats recorded, the ``.py`` is the module.

    RED before the intake change: authentication raised ``distribution contains
    duplicate module seat stubbed_pkg`` and no module was reachable at all.
    """
    distribution = _distribution(
        tmp_path,
        name="stubbed_dist",
        seats={
            "stubbed_pkg/__init__.py": IMPLEMENTATION,
            "stubbed_pkg/__init__.pyi": STUB,
            "stubbed_pkg/inner.py": IMPLEMENTATION,
            "stubbed_pkg/inner.pyi": STUB,
        },
    )
    graph = DependencyArtifactGraph.authenticate(distribution)

    package = graph.modules["stubbed_pkg"]
    inner = graph.modules["stubbed_pkg.inner"]
    # SPECIFIC: the seated source is the implementation's bytes, not the stub's.
    assert package.source_seat == "stubbed_pkg/__init__.py"
    assert package.source == IMPLEMENTATION
    assert inner.source_seat == "stubbed_pkg/inner.py"
    assert inner.source == IMPLEMENTATION
    # The stub seats no module of its own under any spelling.
    assert "stubbed_pkg.inner.pyi" not in graph.modules
    # Both seats stay in the authenticated file record: dropping the stub from
    # the module map must not silently drop it from the artifact preimage.
    assert {item.source_seat for item in graph.files} >= {
        "stubbed_pkg/__init__.py",
        "stubbed_pkg/__init__.pyi",
        "stubbed_pkg/inner.py",
        "stubbed_pkg/inner.pyi",
    }


def test_stub_without_implementation_still_seats_the_stub(tmp_path: Path) -> None:
    """A lone ``.pyi`` (native extension provider) is unchanged: it IS the seat."""
    distribution = _distribution(
        tmp_path,
        name="lonestub_dist",
        seats={
            "lonestub_pkg/__init__.py": IMPLEMENTATION,
            "lonestub_pkg/native.pyi": STUB,
        },
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    assert graph.modules["lonestub_pkg.native"].source == STUB
    assert graph.modules["lonestub_pkg.native"].source_seat == (
        "lonestub_pkg/native.pyi"
    )


def test_module_and_package_seats_are_still_duplicate(tmp_path: Path) -> None:
    """``pkg.py`` beside ``pkg/__init__.py``: different stems, still refused."""
    distribution = _distribution(
        tmp_path,
        name="rival_dist",
        seats={
            "rival_pkg/__init__.py": IMPLEMENTATION,
            "rival_pkg.py": IMPLEMENTATION,
        },
    )
    with pytest.raises(DependencyArtifactAuthenticationError) as caught:
        DependencyArtifactGraph.authenticate(distribution)
    assert str(caught.value) == (
        "distribution contains duplicate module seat rival_pkg"
    )


def test_stub_and_package_seats_are_still_duplicate(tmp_path: Path) -> None:
    """``pkg/m.pyi`` beside ``pkg/m/__init__.py``: a stub is not a package.

    This is the tooth that a suffix-only rule would fail: both seats end in an
    admitted suffix and one of them is a ``.pyi``, but they do not share a stem,
    so nothing here says the stub declares that package.
    """
    distribution = _distribution(
        tmp_path,
        name="stubrival_dist",
        seats={
            "stubrival_pkg/__init__.py": IMPLEMENTATION,
            "stubrival_pkg/m.pyi": STUB,
            "stubrival_pkg/m/__init__.py": IMPLEMENTATION,
        },
    )
    with pytest.raises(DependencyArtifactAuthenticationError) as caught:
        DependencyArtifactGraph.authenticate(distribution)
    assert str(caught.value) == (
        "distribution contains duplicate module seat stubrival_pkg.m"
    )
