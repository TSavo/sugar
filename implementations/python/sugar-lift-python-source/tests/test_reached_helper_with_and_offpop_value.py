"""A manager's construction reaches a helper; that helper's body is constructed.

``pandas.io.pytables.HDFStore.open`` calls ``_tables()``::

    def _tables():
        ...
        import tables
        with suppress(AttributeError):
            _table_file_open_policy_is_strict = (
                tables.file._FILE_OPEN_POLICY == "strict"
            )
        return _table_mod

Two things refused there (#7746):

* ``tables.file._FILE_OPEN_POLICY`` reads a member of a SUBMODULE through the
  package binding (``target-outside-binding``).  ``tables/__init__.py``
  imports ``from .file import ...``, which binds ``file`` as the package
  attribute, so the member is resolved in ``tables.file``; an assigned value
  there is that module's honest open-world (``dynamic-export``) value.  A
  submodule the package never imports is no attribute and still refuses.
* ``with suppress(...)`` inside the reached helper had no derivation: only
  same-module manager classes and factories were derived for a frame's
  with-sites.  Every other head now takes the consumer derivation door,
  selected to exactly the sites left without a derivation, and the With door's
  protocol calls (``__enter__``/``__exit__``, which borrow the head call's
  span) no longer read the head call's source-call row.  A head nothing can
  derive still refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
)
from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

from test_contextmanager_generator_protocol import _function_rows, _imported

_CM = (
    "class CM:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def cm():\n"
    "    helper()\n"
    "    return CM()\n"
)


def _derived(tmp_path: Path, helper: str):
    tree, with_node = _imported(
        tmp_path, _CM + helper, "pass", contextlib_enrolled=True
    )
    refs = with_node.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    return tree, with_node, ref


def test_member_of_an_imported_submodule_is_resolved_there(tmp_path: Path) -> None:
    helper = (
        "def helper():\n"
        "    import json\n"
        "    return json.decoder.WHITESPACE\n"
    )
    tree, with_node, ref = _derived(tmp_path, helper)
    assert not isinstance(ref, ContextManagerResolutionGapV1)
    _consumer, rows = _function_rows(tree, with_node)
    assert rows == [("return", 7)]


def test_member_of_a_submodule_the_package_never_imports_still_refuses(
    tmp_path: Path,
) -> None:
    # Lying twin: ``json/__init__.py`` never imports ``json.tool``, so
    # ``json.tool`` is no attribute of ``json`` and the read stays refused.
    helper = (
        "def helper():\n"
        "    import json\n"
        "    return json.tool.main\n"
    )
    _tree, _with_node, ref = _derived(tmp_path, helper)
    assert isinstance(ref, ContextManagerResolutionGapV1)


def test_imported_manager_with_in_a_reached_helper_is_derived(tmp_path: Path) -> None:
    helper = (
        "from contextlib import suppress\n"
        "def helper():\n"
        "    with suppress(KeyError):\n"
        "        pass\n"
        "    return 1\n"
    )
    tree, with_node, ref = _derived(tmp_path, helper)
    assert not isinstance(ref, ContextManagerResolutionGapV1)
    _consumer, rows = _function_rows(tree, with_node)
    assert rows == [("return", 7)]


def test_underivable_with_in_a_reached_helper_still_refuses(tmp_path: Path) -> None:
    # Lying twin: selecting the helper's with-sites into the derivation door
    # derives nothing it cannot authenticate.  A head over a name bound to no
    # manager stays a named refusal.
    helper = (
        "def helper():\n"
        "    with undefined_manager():\n"
        "        pass\n"
        "    return 1\n"
    )
    with pytest.raises(ContextManagerResolutionConstructionGap):
        tree, with_node, ref = _derived(tmp_path, helper)
        assert isinstance(ref, ContextManagerResolutionGapV1)
        _function_rows(tree, with_node)
