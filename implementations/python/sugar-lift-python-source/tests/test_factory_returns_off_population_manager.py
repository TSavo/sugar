"""A manager factory that returns an off-population call's result is cited.

``pandas._testing.external_error_raised`` is a factory::

    def external_error_raised(expected_exception):
        import pytest
        return pytest.raises(expected_exception, match=None)

``pytest`` is off the enrolled population, so ``pytest.raises(...)`` inside
the factory is an ``OffPopulationSourceCallV1``: two-faced, completing with a
value nobody materialized.  Manager derivation used to force that value to a
floor and panic (``construct_manager_behavior returned object``: missing
callsite body), voiding the whole file -- all 21 files of #7667.

Law: the factory returns exactly what the off-population callee returned, so
the ``with`` over the factory is the ``with`` over that callee: the same
opaque cited manager a direct ``with pytest.raises(...)`` gets, naming the
callee, not the factory.  The head is still evaluated as written, so the
factory's own statements (its prefix) and the callee's raise face stand.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
)
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)

from test_contextmanager_generator_protocol import _function_rows, _imported

_LOCAL_IMPORT_FACTORY = (
    "def cm():\n"
    "    import contextlib\n"
    "    return contextlib.nullcontext()\n"
)
_MODULE_IMPORT_FACTORY = (
    "import contextlib\n"
    "def cm():\n"
    "    return contextlib.nullcontext()\n"
)


def _seated(with_node):
    refs = with_node.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    return ref


def test_local_import_factory_is_cited_as_its_callee(tmp_path: Path) -> None:
    tree, with_node = _imported(
        tmp_path, _LOCAL_IMPORT_FACTORY, "pass", contextlib_enrolled=False
    )
    ref = _seated(with_node)
    assert isinstance(ref, OpaqueCitedContextManagerRefV1)
    assert ref.target_name == "python:contextlib.nullcontext"
    consumer, rows = _function_rows(tree, with_node)
    assert consumer is WithOpaqueCitedManagerSugar
    # The callee's call, enter and exit may each raise; the body falls through.
    assert rows == [("halt", None), ("halt", None), ("halt", None), ("return", 7)]


def test_module_import_factory_is_cited_as_its_callee(tmp_path: Path) -> None:
    tree, with_node = _imported(
        tmp_path, _MODULE_IMPORT_FACTORY, "pass", contextlib_enrolled=False
    )
    ref = _seated(with_node)
    assert isinstance(ref, OpaqueCitedContextManagerRefV1)
    assert ref.target_name == "python:contextlib.nullcontext"


def test_body_raise_still_propagates_through_the_cited_manager(tmp_path: Path) -> None:
    tree, with_node = _imported(
        tmp_path, _LOCAL_IMPORT_FACTORY, "raise KeyError(1)", contextlib_enrolled=False
    )
    _consumer, rows = _function_rows(tree, with_node)
    assert ("halt", "KeyError") in rows
    # A cited manager's suppression is undecided: the raise propagates on one
    # face and is suppressed on the other, which reaches ``return 7``.
    # Asserting it unreachable claimed the cited manager never suppresses.
    assert ("return", 7) in rows


def test_factory_returning_an_enrolled_manager_is_not_cited(tmp_path: Path) -> None:
    # The lying twin: only an OFF-POPULATION result is cited.  A factory that
    # returns a manager class whose source is enrolled still derives it.
    implementation = (
        "class CM:\n"
        "    def __enter__(self):\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        "def cm():\n"
        "    return CM()\n"
    )
    tree, with_node = _imported(tmp_path, implementation, "pass", contextlib_enrolled=False)
    assert not isinstance(_seated(with_node), OpaqueCitedContextManagerRefV1)
    consumer, rows = _function_rows(tree, with_node)
    assert consumer is not WithOpaqueCitedManagerSugar
    assert rows == [("return", 7)]
