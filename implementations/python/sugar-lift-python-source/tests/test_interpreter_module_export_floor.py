"""A builtin interpreter module's export floors on the interpreter's object (#7664).

``itertools`` is compiled into the pinned interpreter, so the stdlib source
root cannot authenticate it.  Its C callables floor as the language-owned
C-extension callable; anything else stays source-absent (``None``).
"""

from __future__ import annotations

import sys

from sugar_lift_python_source.language_owned_c_export import (
    LanguageOwnedCExtensionCallableValue,
    floor_interpreter_module_export,
)
from sugar_lift_py_tests.floor.language_owned_c_type import LanguageOwnedCTypeValue


def test_itertools_callables_floor_as_c_extension_callables():
    assert "itertools" in sys.builtin_module_names
    for name in ("chain", "product", "count", "islice"):
        floor = floor_interpreter_module_export(f"python:itertools.{name}")
        # A static C class floors as the language-owned C type; either face
        # is keyed by the interpreter's own (module, name).
        assert isinstance(
            floor, (LanguageOwnedCTypeValue, LanguageOwnedCExtensionCallableValue)
        ), name
        assert floor.module_name == "itertools"
        assert getattr(floor, "type_name", getattr(floor, "exported_name", None)) == name


def test_non_builtin_or_malformed_targets_stay_source_absent():
    for target in (
        "python:json.dumps",  # has source: the export door owns it
        "python:itertools.chain.from_iterable",  # not a module member
        "python:itertools",
        "python:itertools.no_such_member",
        "itertools.chain",
        None,
    ):
        assert floor_interpreter_module_export(target) is None, target
