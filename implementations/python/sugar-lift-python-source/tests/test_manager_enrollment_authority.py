from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def test_missing_enrolled_roster_refuses_instead_of_path_seed(tmp_path: Path) -> None:
    source_file = SimpleNamespace(
        root=SimpleNamespace(unit=SimpleNamespace(construction_context=None))
    )
    with pytest.raises(
        TypeError,
        match="session construction requires an enrolled distribution roster",
    ):
        populate_source_derived_resource_refs(
            source_file,
            root=tmp_path,
            path=tmp_path / "pandas" / "_config" / "config.py",
        )


def test_supplied_enrolled_roster_is_accepted_and_never_widened(
    tmp_path: Path,
) -> None:
    source_file = SimpleNamespace(
        root=SimpleNamespace(unit=SimpleNamespace(construction_context=None)),
        unit=SimpleNamespace(imported_modules=lambda: frozenset()),
    )
    roster = frozenset({"blake3-512:listed"})
    session = SourceResolutionSession(enrolled_distributions=roster)
    populate_source_derived_resource_refs(
        source_file,
        root=tmp_path,
        path=tmp_path / "pandas" / "_config" / "config.py",
        session=session,
    )
    # Populate has no door that adds to the population (#7796).
    assert session.enrolled_distributions == roster


def test_populate_takes_no_distribution(tmp_path: Path) -> None:
    source_file = SimpleNamespace(
        root=SimpleNamespace(unit=SimpleNamespace(construction_context=None))
    )
    with pytest.raises(TypeError):
        populate_source_derived_resource_refs(
            source_file,
            root=tmp_path,
            path=tmp_path / "x.py",
            distribution="pandas",
            session=SourceResolutionSession(enrolled_distributions=frozenset()),
        )
