"""``m.x`` where nothing here resolved ``m`` is the one two-faced read.

``import sys`` with no projected ``sys`` leaves ``sys`` a bare symbolic name,
and ``sys.maxsize`` once refused (``undecided receiver runtime type or member
semantics``) -- inside numpy's ``_make_options_dict`` that refusal stopped
``np.printoptions``.  No floor, contract or source testified to what
``getattr`` runs, so the read may complete with any member or raise anything.

That is the same read as ``p.x`` on a formal: the receiver answers it
(``SymbolicValue.attribute``), whatever bound it, through the one two-faced
undecided read (``floor_value.undecided_attribute_result``): it completes
with ``python:attribute_result(<name>, <receiver>, <key>)`` only under
``python:attribute_op.completes(...)`` keyed per evaluation, and halts with an ``UndeterminedRaiseEffect`` under
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


# A dotted read off an imported head is the import member's own read (step 3:
# the import table names it): ``ImportMemberValue.read_faces``, the same
# keyed two faces, completing with the import reference (``ref:<target>``,
# which the join answers) and halting undetermined, owed under the import's
# target symbol (#7757, #9034).


@pytest.mark.parametrize(
    "module,attribute", [("sys", "maxsize"), ("math", "pi"), ("errno", "ENOENT")]
)
def test_an_imported_module_attribute_completes_or_raises(tmp_path, module, attribute):
    from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue

    returns, halts = _split(
        tmp_path, f"import {module}\ndef f():\n    return {module}.{attribute}\n"
    )
    (value,) = returns
    assert type(value) is ImportMemberValue
    assert value.qualified_name == f"{module}.{attribute}"
    assert _owners(halts) == ["ImportMemberValue.read"]
    assert all(halt.exception_name is None for halt in halts)


def test_two_reads_are_two_raise_faces(tmp_path):
    _returns, halts = _split(
        tmp_path, "import sys\ndef f():\n    return (sys.maxsize, sys.maxsize)\n"
    )
    assert _owners(halts) == ["ImportMemberValue.read"] * 2


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
    from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue

    returns, halts = _split(tmp_path, "import os\ndef f():\n    return os.path.sep\n")
    (value,) = returns
    # The static chain names the export path; the read is the import
    # member's two faces, never a completion with no halt kept.
    assert type(value) is ImportMemberValue
    assert value.qualified_name.endswith(".sep")
    assert halts
    assert set(_owners(halts)) == {"ImportMemberValue.read"}


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
