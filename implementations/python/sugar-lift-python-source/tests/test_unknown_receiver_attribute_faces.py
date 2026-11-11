"""``m.x`` where nothing here resolved ``m`` is two-faced.

``import sys`` with no projected ``sys`` leaves ``sys`` a bare symbolic name,
and ``sys.maxsize`` refused (``undecided receiver runtime type or member
semantics``) -- inside numpy's ``_make_options_dict`` that refusal stopped
``np.printoptions``.  The module binds the name only by an import, so no
floor, contract or source testified to what ``getattr`` runs: the read
completes under ``python:unknown_attribute.completes(...)`` with its own
``python:attribute_result`` and halts with an ``UndeterminedRaiseEffect``
(``UnknownAttribute:<dotted>``) under the complement -- the #7585 law that
``sys.getrecursionlimit()`` already follows as an unknown callee.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.outcome import Completed, Halted

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        halt.producer_node_owner
        for halt in halts
        if isinstance(halt, UndeterminedRaiseEffect)
    )


@pytest.mark.parametrize(
    "module,attribute", [("sys", "maxsize"), ("math", "pi"), ("errno", "ENOENT")]
)
def test_an_imported_module_attribute_completes_or_raises(tmp_path, module, attribute):
    returns, halts = _split(
        tmp_path, f"import {module}\ndef f():\n    return {module}.{attribute}\n"
    )
    (value,) = returns
    assert isinstance(value, SymbolicValue)
    assert value.term.name == "python:attribute_result"
    assert _owners(halts) == [f"UnknownAttribute:{module}.{attribute}"]


def test_two_reads_are_two_unknowns(tmp_path):
    returns, halts = _split(
        tmp_path, "import sys\ndef f():\n    return (sys.maxsize, sys.maxsize)\n"
    )
    (pair,) = returns
    left, right = pair.elements
    assert left != right
    assert _owners(halts) == ["UnknownAttribute:sys.maxsize"] * 2


def test_the_raise_reaches_an_except_arm(tmp_path):
    source = (
        "import sys\n"
        "def f():\n"
        "    try:\n"
        "        x = sys.maxsize\n"
        "    except AttributeError:\n"
        "        return 0\n"
        "    return 1\n"
    )
    returns, _halts = _split(tmp_path, source)
    assert TermValue(0) in returns and TermValue(1) in returns


def test_a_dotted_read_is_two_reads(tmp_path):
    returns, halts = _split(tmp_path, "import os\ndef f():\n    return os.path.sep\n")
    (value,) = returns
    assert value.term.name == "python:attribute_result"
    assert _owners(halts) == ["UnknownAttribute:os.path", "UnknownAttribute:os.path.sep"]


def test_a_formal_receiver_keeps_its_own_law(tmp_path):
    try:
        returns, halts = _split(tmp_path, "def f(p):\n    return p.x\n")
    except BaseException as exc:  # a refusal is its own law, not this one
        assert "UnknownAttribute" not in str(exc)
        return
    assert not any("UnknownAttribute" in owner for owner in _owners(halts))


def test_a_name_the_module_assigns_is_not_unknown(tmp_path):
    source = "import sys\nm = sys\ndef f():\n    return m.maxsize\n"
    try:
        _returns, halts = _split(tmp_path, source)
    except BaseException as exc:
        assert "UnknownAttribute" not in str(exc)
        return
    assert not any("UnknownAttribute:m." in owner for owner in _owners(halts))
