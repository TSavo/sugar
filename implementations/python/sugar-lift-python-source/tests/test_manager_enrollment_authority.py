from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_python_source.manager_summary_derivation import (
    _qualified_enrollment_coordinate,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def test_package_seat_uses_authenticated_distribution(tmp_path: Path) -> None:
    workspace = tmp_path / "site-packages" / "pandas"
    path = workspace / "_config" / "config.py"
    path.parent.mkdir(parents=True)
    path.write_text("x = 1\n", encoding="utf-8")

    assert (
        _qualified_enrollment_coordinate(
            path,
            source_workspace_root=workspace,
            distribution="pandas",
        )
        == "pandas/_config/config.py"
    )

    assert (
        _qualified_enrollment_coordinate(
            path,
            source_workspace_root=workspace.parent,
            distribution="pandas",
        )
        == "pandas/_config/config.py"
    )


def test_missing_distribution_refuses_instead_of_bare_segment(tmp_path: Path) -> None:
    path = tmp_path / "pandas" / "_config" / "config.py"
    path.parent.mkdir(parents=True)
    with pytest.raises(ValueError, match="distribution authority is required"):
        _qualified_enrollment_coordinate(
            path,
            source_workspace_root=tmp_path,
            distribution=None,
        )


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


def test_supplied_enrolled_roster_is_accepted(tmp_path: Path) -> None:
    source_file = SimpleNamespace(
        root=SimpleNamespace(unit=SimpleNamespace(construction_context=None))
    )
    populate_source_derived_resource_refs(
        source_file,
        root=tmp_path,
        path=tmp_path / "pandas" / "_config" / "config.py",
        source_workspace_root=tmp_path / "pandas",
        distribution="pandas",
        session=SourceResolutionSession(enrolled_distributions=frozenset({"pandas"})),
    )
