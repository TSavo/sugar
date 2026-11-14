"""A memo row is served only where the ambient values it read still hold.

#7838 / #7757 inventory item 44: a row records every ambient value its
computation read (``AmbientVar.get``, ``member in AmbientSet``) and is served
only where each is equal now.  A row that read none is served everywhere.  A
value the computation set itself is not ambient to it while that set is in
force; once reset, a later read records it.
"""

from __future__ import annotations

from sugar_source_tree import nodes
from sugar_source_tree.construction_cache import (
    AmbientSet,
    AmbientVar,
    close_row,
    open_row,
    serve,
)

_VAR = AmbientVar("test_memo_row_ambient_var", default="plain")
_SET = AmbientSet("test_memo_row_ambient_set")
_REPORTER = object()


def _compute(table: dict, key: tuple, construct) -> object:
    row = serve(table, key, _REPORTER)
    if row is not None:
        return row.value
    computation = open_row()
    value = construct()
    close_row(table, key, computation, _REPORTER, value=value)
    return value


def test_a_row_that_reads_an_ambient_var_is_recomputed_where_it_differs():
    table: dict = {}
    computed: list = []

    def construct():
        computed.append(_VAR.get())
        return object()

    first = _compute(table, ("k",), construct)
    assert _compute(table, ("k",), construct) is first

    token = _VAR.set("projected")
    try:
        second = _compute(table, ("k",), construct)
        assert second is not first
        assert _compute(table, ("k",), construct) is second
    finally:
        _VAR.reset(token)

    assert _compute(table, ("k",), construct) is first
    assert computed == ["plain", "projected"]


def test_a_row_that_reads_set_membership_is_recomputed_where_it_differs():
    table: dict = {}

    def construct():
        return ("open" if "f" in _SET else "closed", object())

    closed = _compute(table, ("k",), construct)
    _SET.add("f")
    try:
        opened = _compute(table, ("k",), construct)
    finally:
        _SET.discard("f")
    assert closed[0] == "closed"
    assert opened[0] == "open"
    assert _compute(table, ("k",), construct) is closed


def test_a_row_that_reads_no_ambient_is_served_everywhere():
    table: dict = {}
    first = _compute(table, ("k",), object)

    token = _VAR.set("projected")
    _SET.add("f")
    try:
        assert _compute(table, ("k",), object) is first
    finally:
        _SET.discard("f")
        _VAR.reset(token)
    assert _compute(table, ("k",), object) is first


def test_a_value_the_row_set_itself_is_ambient_again_after_its_reset():
    computation = open_row()
    token = _VAR.set("own")
    assert _VAR.get() == "own"
    _VAR.reset(token)
    assert _VAR.get() == "plain"
    row = close_row({}, ("k",), computation, _REPORTER, value=None)
    assert row.reads == {(_VAR, None): "plain"}


def test_a_member_the_row_added_itself_is_ambient_again_after_its_discard():
    computation = open_row()
    _SET.add("f")
    assert "f" in _SET
    _SET.discard("f")
    assert "f" not in _SET
    row = close_row({}, ("k",), computation, _REPORTER, value=None)
    assert row.reads == {(_SET, "f"): False}


def test_the_module_execution_site_is_read_on_the_row_in_flight():
    table: dict = {}
    first = _compute(table, ("k",), nodes.current_module_execution_site)
    assert first is None
    (row,) = table[("k",)]
    assert row.reads == {(nodes._MODULE_EXECUTION_SITE, None): None}

    site = object()
    served = nodes.construct_at_module_execution_site(
        site, lambda: serve(table, ("k",), _REPORTER)
    )
    assert served is None


def test_a_site_the_construction_sets_is_its_own():
    computation = open_row()
    nodes.construct_at_module_execution_site(
        None, nodes.current_module_execution_site
    )
    row = close_row({}, ("k",), computation, _REPORTER, value=None)
    assert row.reads == {}
