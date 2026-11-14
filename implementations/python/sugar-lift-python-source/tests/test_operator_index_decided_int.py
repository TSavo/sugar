"""``operator.index`` on an exact int is that int (CPython's own source).

``operator.index`` is ``_operator.index`` (Modules/_operator.c:
``return PyNumber_Index(a);``).  In Objects/abstract.c, ``_PyNumber_Index``
returns ``Py_NewRef(item)`` for an int, and ``PyNumber_Index`` copies only a
non-exact result.  So an exact ``int`` comes back unchanged and nothing is
raised.  The stdlib ``operator`` module is off the enrolled population, so
the call used to be two-faced (``OffPopulationCall:python:operator.index``,
or the unanswered ``UnknownCallee:operator.index`` from a consumer)
even for ``operator.index(3)``, which is numpy's ``_make_options_dict`` under
``precision=3``.  A bool, a str, or an unknown value stays two-faced.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

from test_undetermined_raise_except_matching import _exits


def _faces(tmp_path, operand):
    return _exits(
        tmp_path,
        f"import operator\ndef f():\n    if operator.index({operand}) == 3:\n"
        "        return 7\n    return 8\n",
    ).exits


def _owners(exits):
    return [
        face.effect.producer_node_owner for face in exits if isinstance(face, Halted)
    ]


def test_an_exact_int_passes_through(tmp_path):
    exits = _faces(tmp_path, "3")
    assert _owners(exits) == []
    (done,) = exits
    assert isinstance(done, Completed)
    returns = [entry.value.value for entry in done.value.record.statements]
    assert returns == [7]


@pytest.mark.parametrize("operand", ["True", "'3'"])
def test_anything_else_stays_two_faced(tmp_path, operand):
    owners = _owners(_faces(tmp_path, operand))
    assert any(owner.endswith("operator.index") for owner in owners)
