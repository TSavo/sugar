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

from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_python_source.dependency_artifact import (
    ResolvedPythonObjectV1,
    authenticate_dependency_top_level,
    module_alias_binding,
)
from sugar_source_tree.nodes import Attribute

from test_import_value_use_frame_seating import (
    _consumer,
    _distribution,
    _frame_for_box_expected,
)

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


def _frame_with_os(tmp_path: Path, helpers: str):
    """The seating harness, with ``os``'s artifact already authenticated."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_lift_python_source.source_call_preconstruction import (
        populate_source_visible_call_frames,
    )
    from sugar_source_tree.nodes import Call

    distribution = _distribution(tmp_path, helpers)
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import box_expected, ArrayType\n"
        "actual = box_expected((1,), ArrayType)\n",
    )
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({distribution.metadata["Name"]})
    )
    session.dependency_graphs["os"] = authenticate_dependency_top_level("os")
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        session=session,
    )
    span = call.line_col_span()
    return context.source_call_frames[
        SourceFragmentCoordinateV1(
            source_file.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ]


@posix_only
def test_os_path_member_resolves_in_posixpath(tmp_path: Path) -> None:
    frame = _frame_with_os(
        tmp_path,
        "import os\n"
        "def box_expected(expected, box_cls=None):\n"
        "    expand = os.path.expanduser\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    resolved = [
        value
        for value in frame.owner.unit._import_value_use_resolutions.values()
        if isinstance(value, ResolvedPythonObjectV1)
    ]
    assert [(item.module_name, item.definition.name) for item in resolved] == [
        ("posixpath", "expanduser")
    ]


def test_dotted_module_alias_read_is_an_attribute_read(tmp_path: Path) -> None:
    frame = _frame_for_box_expected(
        tmp_path,
        "def box_expected(expected, box_cls=None):\n"
        "    import urllib.request\n"
        "    opener = urllib.request\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    (read,) = [
        node
        for node in frame.owner.walk()
        if isinstance(node, Attribute) and node.attr == "request"
    ]
    span = read.line_col_span()
    # The module-alias receipt IS seated at this read; it names no member.
    seated = read.unit.import_value_use_resolution(
        (span.start_line, span.start_col, span.end_line, span.end_col)
    )
    assert type(seated).__name__ == "AuthenticatedImportUseV1"
    assert type(read.sugar()) is AttributeSugar
