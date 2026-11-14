"""An export the source binds dynamically, decided by the interpreter.

``os.path.dirname`` is ``target-outside-binding`` through the dynamic
``os.path`` binding.  The running, pin-authenticated interpreter decides it:
``os.path`` IS ``posixpath``, and ``posixpath.dirname`` resolves to its stdlib
source, which the population membrane then cites off-population.  What a
callee is written in is never asked (#7757 item 3).
"""

from __future__ import annotations

from types import SimpleNamespace

_CID = "blake3-512:" + "0" * 128


def _session():
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    return SourceResolutionSession(enrolled_distributions=frozenset({"pandas"}))


def _outside(target):
    from sugar_lift_python_source.manager_construction import (
        _resolve_through_runtime_module_alias,
    )

    return _resolve_through_runtime_module_alias(
        SimpleNamespace(
            kind="target-outside-binding", module_name="os", import_binding_cid=_CID
        ),
        SimpleNamespace(target_symbol=target),
        session=_session(),
    )


def test_os_path_member_resolves_in_the_module_the_interpreter_bound():
    from sugar_lift_python_source.manager_construction import _graph_is_off_population

    resolved, graph = _outside("python:os.path.dirname")
    assert resolved.module_name == "posixpath"
    # Stdlib source: the projection door cites it off-population.
    assert _graph_is_off_population(graph, session=_session())


def test_alias_hop_needs_a_module_and_a_real_export():
    assert _outside("python:os.getcwd") is None  # no module alias on the path
    assert _outside("python:os.path.no_such_export") is None
