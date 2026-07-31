"""Module export resolution consumes explicit package-disposition testimony."""

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.import_binding import authenticated_module_exports


def _exports(tmp_path, *, module_is_package):
    source_path = tmp_path / "same_source.py"
    source_path.write_text("from .provider import pair\n", encoding="utf-8")
    source, _filename, source_cid = path_source(str(source_path))
    return authenticated_module_exports(
        tmp_path,
        source_path,
        source,
        source_cid,
        module_is_package=module_is_package,
    )


def test_package_disposition_resolves_relative_export_from_the_package_itself(tmp_path):
    rows = _exports(tmp_path, module_is_package=True)

    assert [row["targetSymbol"] for row in rows] == [
        "python:same_source.provider.pair"
    ]


def test_module_disposition_resolves_relative_export_from_its_parent(tmp_path):
    rows = _exports(tmp_path, module_is_package=False)

    assert [row["targetSymbol"] for row in rows] == ["python:provider.pair"]


def test_package_disposition_has_no_default_or_truthy_fallback(tmp_path):
    with pytest.raises(TypeError, match="exact authenticated bool testimony"):
        _exports(tmp_path, module_is_package=1)
