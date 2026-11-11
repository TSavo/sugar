"""A factory returning managers of different kinds enters each under its guard.

``pandas._testing.raises_chained_assignment_error`` is::

    if PYPY:
        return nullcontext()
    return assert_produces_warning(...)

a class manager under one guard and a ``@contextmanager`` generator manager
under its complement.  Picking either claims it on every path (#7692 refused
that).  Law (#7669): construct each face's manager by the door its kind has,
enter each manager face of the With's own reduction of the factory under that
face's guard, and union the exit sets.  A face whose value is not a manager
keeps the named refusal.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithManagerPartitionSugar,
)
from sugar_lift_python_source.manager_protocol_construction import (
    GuardedManagerPartitionProtocolV1,
)

from test_contextmanager_generator_protocol import _function_rows, _imported

_FACTORY = (
    "import contextlib\n"
    "import platform\n"
    "ENABLED = platform.python_implementation() == 'PyPy'\n"
    "class Quiet:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "@contextlib.contextmanager\n"
    "def loud():\n"
    "    try:\n"
    "        yield 2\n"
    "    except KeyError:\n"
    "        pass\n"
    "def cm():\n"
    "    if ENABLED:\n"
    "        return Quiet()\n"
    "    return loud()\n"
)


def _seated(with_node):
    refs = with_node.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    return ref


def test_each_face_manager_is_constructed(tmp_path: Path) -> None:
    _tree, with_node = _imported(tmp_path, _FACTORY, "pass", contextlib_enrolled=True)
    ref = _seated(with_node)
    assert isinstance(ref, SourceDerivedContextManagerRefV1), ref
    protocol = ref.protocol
    assert isinstance(protocol, GuardedManagerPartitionProtocolV1)
    assert protocol.class_protocol is not None
    assert len(protocol.generator_protocols) == 1
    assert type(with_node.sugar()) is WithManagerPartitionSugar


def test_exit_sets_are_the_union_of_the_guarded_faces(tmp_path: Path) -> None:
    # The body raises KeyError.  Under the class face Quiet.__exit__ returns
    # False: the KeyError leaves f.  Under the generator face the generator's
    # ``except KeyError`` suppresses it: f returns 7.  Both, never one.
    tree, with_node = _imported(
        tmp_path, _FACTORY, "raise KeyError(1)", contextlib_enrolled=True
    )
    consumer, rows = _function_rows(tree, with_node)
    assert consumer is WithManagerPartitionSugar
    assert ("halt", "KeyError") in rows
    assert ("return", 7) in rows


def test_body_falls_through_both_faces(tmp_path: Path) -> None:
    tree, with_node = _imported(tmp_path, _FACTORY, "pass", contextlib_enrolled=True)
    _consumer, rows = _function_rows(tree, with_node)
    assert ("return", 7) in rows
    assert ("halt", "KeyError") not in rows
