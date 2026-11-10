"""numpy.errstate is a static export once If and __all__ algebra close."""

from __future__ import annotations

from sugar_lift_python_source.dependency_artifact import (
    ResolvedPythonObjectV1,
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.dependency_export_adapter import resolve_export
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def test_numpy_errstate_resolves_to_the_ufunc_config_class() -> None:
    graph = authenticate_dependency_top_level("numpy")
    session = SourceResolutionSession(enrolled_distributions=frozenset({"numpy"}))
    result = resolve_export(
        graph,
        "bind-cid",
        "numpy",
        "errstate",
        (),
        frozenset(),
        session=session,
    )
    assert isinstance(result, ResolvedPythonObjectV1), result
    assert result.module_name == "numpy._core._ufunc_config"
    assert result.definition.name == "errstate"
