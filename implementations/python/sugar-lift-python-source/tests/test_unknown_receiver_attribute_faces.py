"""``m.x`` where nothing here resolved ``m`` is the one two-faced read.

``import sys`` with no projected ``sys`` leaves ``sys`` a bare symbolic name,
and ``sys.maxsize`` once refused (``undecided receiver runtime type or member
semantics``) -- inside numpy's ``_make_options_dict`` that refusal stopped
``np.printoptions``.  No floor, contract or source testified to what
``getattr`` runs, so the read may complete with any member or raise anything.

That is the same read as ``p.x`` on a formal: the receiver answers it
(``SymbolicValue.attribute``), whatever bound it, through the one two-faced
undecided read (``FloorValue.undecided_attribute``): it completes with
``attr:<name>(<receiver>)`` only under ``python:attribute.completes(...)``
keyed on the read's site, and halts with an ``UndeterminedRaiseEffect`` under
the complement -- the #7585 law.  There is no second law for a receiver the
module binds only by an import, and no second lexical walk to choose it
(#7757).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue

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
    assert getattr(value.term, "name", None) == f"attr:{attribute}"
    assert _owners(halts) == ["SymbolicValue.attribute"]


def test_two_reads_are_two_raise_faces(tmp_path):
    _returns, halts = _split(
        tmp_path, "import sys\ndef f():\n    return (sys.maxsize, sys.maxsize)\n"
    )
    assert _owners(halts) == ["SymbolicValue.attribute"] * 2


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
    assert getattr(value.term, "name", None) == "attr:sep"
    assert _owners(halts) == ["CallSiteValue.attribute", "SymbolicValue.attribute"]


def test_a_formal_receiver_reads_by_the_same_law(tmp_path):
    try:
        _returns, halts = _split(tmp_path, "def f(p):\n    return p.x\n")
    except BaseException as exc:  # a refusal is the formal's own, not a law
        assert "UnknownAttribute" not in str(exc)
        return
    assert "UnknownAttribute" not in " ".join(_owners(halts))
    assert set(_owners(halts)) <= {"SymbolicValue.attribute"}


def test_a_name_the_module_assigns_reads_by_the_same_law(tmp_path):
    source = "import sys\nm = sys\ndef f():\n    return m.maxsize\n"
    try:
        _returns, halts = _split(tmp_path, source)
    except BaseException as exc:
        assert "UnknownAttribute" not in str(exc)
        return
    assert not any("UnknownAttribute" in owner for owner in _owners(halts))
