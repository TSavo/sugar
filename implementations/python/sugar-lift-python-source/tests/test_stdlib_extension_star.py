"""A C extension in the interpreter's own ``lib-dynload`` is interpreter-owned."""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_python_source.dependency_export_adapter import (
    _builtin_module_star_names,
    _cannot_raise_during_module_init,
    _is_stdlib_extension_module,
)
from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
)

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def test_stdlib_extension_is_recognized_from_its_spec_origin() -> None:
    assert _is_stdlib_extension_module("_decimal")
    # Built-in (no file), pure-Python stdlib, and third-party are not.
    assert not _is_stdlib_extension_module("posix")
    assert not _is_stdlib_extension_module("json")
    assert not _is_stdlib_extension_module("numpy")
    assert not _is_stdlib_extension_module("no_such_module_anywhere")


def test_stdlib_extension_star_publishes_its_runtime_public_names() -> None:
    names = _builtin_module_star_names("_decimal")
    assert {"localcontext", "Decimal", "getcontext"} <= names
    assert _builtin_module_star_names("numpy") == frozenset()


def test_import_from_an_interpreter_c_module_cannot_raise() -> None:
    def first(source: str):
        return ast.parse(source).body[0]

    assert _cannot_raise_during_module_init(first("from _decimal import *\n"))
    assert _cannot_raise_during_module_init(
        first("from _decimal import __version__\n")
    )
    # A name the module does not define, or a non-interpreter module, may raise.
    assert not _cannot_raise_during_module_init(
        first("from _decimal import not_a_real_name\n")
    )
    assert not _cannot_raise_during_module_init(first("from numpy import *\n"))
    assert not _cannot_raise_during_module_init(first("from json import *\n"))


def test_decimal_localcontext_resolves_to_its_c_origin(tmp_path: Path) -> None:
    # decimal.py is ``try: from _decimal import * except ImportError: ...``.
    # The interpreter decides the try arm, so the export is no longer dynamic;
    # it names a module no artifact holds source for, so the manager is not
    # bridged and is cited naming its import target.
    source = (
        "import decimal\n"
        "def f():\n"
        "    with decimal.localcontext() as ctx:\n"
        "        pass\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (reference,) = refs.values()
    assert isinstance(reference, OpaqueCitedContextManagerRefV1)
    assert reference.roster.resolution_kind == "call-target-off-population"
