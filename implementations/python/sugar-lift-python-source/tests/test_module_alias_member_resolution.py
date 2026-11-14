"""``os.path.expanduser`` is a member of the module ``os`` binds as ``path``.

``pandas.io.common.get_handle`` reads ``os.path.expanduser``.  ``os.path`` is no
submodule in ``os``'s artifact: ``os`` binds it by ``import posixpath as path``
(``import ntpath as path`` on nt).  The value-use receipt named a target the
binding could not reach (``target-outside-binding``), so every ``with
get_handle(...)`` stood on that gap (#7665).

Law: when a module binds a name by ``import X as name`` and the running
interpreter registered exactly that module as ``module.name``, a member of
``module.name`` is the member of ``X``, resolved in ``X``'s own artifact through
the one export door.  Source and interpreter must agree; nothing is imported.

The dotted module alias itself (``import urllib.request`` then the read
``urllib.request``) names no member: it is the attribute read of the bound
package, never an empty-path import member.
"""

from __future__ import annotations

import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_python_source.dependency_artifact import module_alias_binding

posix_only = pytest.mark.skipif(
    sys.modules["os"].path is not posixpath, reason="os.path is posixpath here"
)


@posix_only
def test_os_binds_path_to_posixpath() -> None:
    graph = authenticate_dependency_top_level("os")
    assert module_alias_binding(graph, "os", "path") == "posixpath"


def test_a_name_not_bound_by_import_as_is_no_alias() -> None:
    # ``environ`` is assigned in os, not imported as a module alias.
    graph = authenticate_dependency_top_level("os")
    assert module_alias_binding(graph, "os", "environ") is None


@dataclass(frozen=True)
class _Module:
    source: str


@dataclass(frozen=True)
class _Graph:
    modules: dict


def test_source_and_interpreter_must_agree() -> None:
    # The source binds ``path`` by importing posixpath, but the interpreter
    # registered no ``lyingmod.path``: no alias.
    graph = _Graph({"lyingmod": _Module("import posixpath as path\n")})
    assert module_alias_binding(graph, "lyingmod", "path") is None


def test_an_import_inside_a_function_binds_no_module_name() -> None:
    graph = _Graph({"os": _Module("def f():\n    import posixpath as path\n")})
    assert module_alias_binding(graph, "os", "path") is None
