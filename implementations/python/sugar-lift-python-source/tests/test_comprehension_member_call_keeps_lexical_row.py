"""A comprehension member that calls a local function is still that call.

A list comprehension over a decided sequence dissolves into one copy of its
element per member (#7601).  The copy is a fresh backend identity over the
element's span and kind, so it joins the element's published lexical-call
enrollment by occurrence -- and the producer-owned row that names the called
definition has to ride along with it, exactly as ``Call.substitute`` carries
it through a rewrite.  Before, the copy was enrolled with no row, and reducing
it ended in a BackendDefect (``0 lexical rows for one enrolled call
occurrence``) instead of a terminal: pandas
``tests/io/excel/test_writers.py:163`` (#7673).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.floor.list_value import ListValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _returns(rows):
    return [payload for kind, payload, _guard in rows if kind == "return"]


def test_member_call_to_module_function_projects_its_body(tmp_path: Path) -> None:
    source = (
        "def tdf(name):\n"
        "    return [name, name]\n"
        "def f():\n"
        "    sheets = ['AAA', 'BBB']\n"
        "    dfs = [tdf(s) for s in sheets]\n"
        "    return dict(zip(sheets, dfs))\n"
    )
    rows = _rows(_exits(tmp_path, source))
    assert len(_returns(rows)) == 1, rows


def test_member_call_to_nested_function_projects_its_body(tmp_path: Path) -> None:
    # The board file's shape: ``tdf`` is defined inside the test.  A call to a
    # nested def carries the frame it read from its definition, read once at
    # construction (never read again out of the seated-frame table at
    # desugar), so the member call projects its body as a module function's
    # does -- never a BackendDefect, never a refusal for a frame no table
    # seats.
    source = (
        "def f():\n"
        "    def tdf(name):\n"
        "        return [name, name]\n"
        "    sheets = ['AAA', 'BBB']\n"
        "    dfs = [tdf(s) for s in sheets]\n"
        "    return dict(zip(sheets, dfs))\n"
    )
    rows = _rows(_exits(tmp_path, source))
    assert len(_returns(rows)) == 1, rows


def test_member_calls_are_each_their_own_evaluation(tmp_path: Path) -> None:
    # The lying twin: retaining the row must not merge the members.  Each
    # member is the local function's body run on ITS item.
    source = (
        "def tdf(name):\n"
        "    return [name]\n"
        "def f():\n"
        "    return [tdf(s) for s in ['AAA', 'BBB']]\n"
    )
    rows = _rows(_exits(tmp_path, source))
    (returned,) = _returns(rows)
    assert isinstance(returned, ListValue), returned
    assert len(returned.elements) == 2
    assert returned.elements[0] != returned.elements[1]
