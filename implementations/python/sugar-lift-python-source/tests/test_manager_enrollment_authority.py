from pathlib import Path

import pytest

from sugar_lift_python_source.manager_summary_derivation import (
    _qualified_enrollment_coordinate,
)


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


def test_missing_distribution_refuses_instead_of_bare_segment(tmp_path: Path) -> None:
    path = tmp_path / "pandas" / "_config" / "config.py"
    path.parent.mkdir(parents=True)
    with pytest.raises(ValueError, match="distribution authority is required"):
        _qualified_enrollment_coordinate(
            path,
            source_workspace_root=tmp_path,
            distribution=None,
        )
