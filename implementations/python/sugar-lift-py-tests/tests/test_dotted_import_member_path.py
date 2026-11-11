"""``import a.b`` binds ``a``; ``a.b.x`` is ``x`` of the module ``a.b``.

The binding's module is ``a.b`` (the import guarantees it is loaded) while the
local name is the package ``a``.  A use's member path is therefore read after
the ``b`` the use spells: ``a.b.x`` -> ``python:a.b.x`` (it used to compose
``python:a.b.b.x``, which no module defines).  ``a.y`` and the bare ``a`` are
the package, which this binding does not name, so they get no receipt from it.
``import a.b as c`` binds ``a.b`` itself and is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.source_oracle import path_source


def _receipts(tmp_path: Path, text: str):
    path = tmp_path / "m.py"
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    calls, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    values, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    return (
        sorted(r.target_symbol for r in calls),
        sorted(r.target_symbol for r in values),
    )


def test_a_member_of_the_imported_submodule_names_that_module(tmp_path):
    calls, values = _receipts(
        tmp_path, "import pkg.sub\ndef f():\n    return pkg.sub.g(1)\n"
    )
    assert calls == ["python:pkg.sub.g"]
    assert "python:pkg.sub.g" in values
    assert not any("sub.sub" in symbol for symbol in calls + values)


def test_a_member_of_the_package_is_not_this_bindings_use(tmp_path):
    calls, values = _receipts(
        tmp_path, "import pkg.sub\ndef f():\n    return pkg.other(1)\n"
    )
    assert calls == []
    assert values == []


def test_the_bare_package_name_is_not_the_submodule(tmp_path):
    _calls, values = _receipts(tmp_path, "import pkg.sub\nx = pkg\n")
    assert values == []


def test_an_aliased_dotted_import_binds_the_submodule(tmp_path):
    calls, values = _receipts(
        tmp_path, "import pkg.sub as s\ndef f():\n    return s.g(1)\n"
    )
    assert calls == ["python:pkg.sub.g"]
    assert "python:pkg.sub.g" in values


def test_a_plain_import_is_unchanged(tmp_path):
    calls, _values = _receipts(
        tmp_path, "import pkg\ndef f():\n    return pkg.sub.g(1)\n"
    )
    assert calls == ["python:pkg.sub.g"]
