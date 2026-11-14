"""A call whose callee nothing resolved may raise, and each one returns its
own unknown.

``h()`` with ``h`` unbound, ``y()`` with ``y`` a formal, and
``random.random()`` whose module member the import door did not cite all fell
through to the bare ``call:<name>(..)`` / ``py.call(..)`` coordinate and always
completed: an ``except`` arm around them was unreachable, and ``(h(), h())``
claimed both calls return the same object.  Nothing testified to what runs, so
the call is two-faced (the #7585 law): it completes under
``python:unknown_callee_call.completes(python:unknown_callee_call(callee,
site))`` with ``python:call_result(<call term>, <occurrence>)``, and halts with
an ``UndeterminedRaiseEffect`` (owner ``UnknownCallee:<callee>``) under the
complement.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.unanswered_calls import owed_calls

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits
from test_unprojected_method_call_faces import _owners, _split


def _values(returns):
    return {value.value for value in returns}


def test_an_undefined_name_call_may_raise(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return h()\n")
    (value,) = returns
    term = value.to_term(owner="test")
    assert term.name == "python:call_result"
    assert term.args[0].name == "call:h"
    assert _owners(halts) == ["UnknownCallee:h"]


def test_an_unread_assignment_keeps_its_raise(tmp_path):
    # #7600: the right-hand side is evaluated at the assignment.
    returns, halts = _split(tmp_path, "def f():\n    a = h()\n    return 1\n")
    assert returns == [TermValue(1)]
    assert _owners(halts) == ["UnknownCallee:h"]


def test_its_raise_reaches_an_except_arm(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        h()\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    return 1\n"
    )
    returns, halts = _split(tmp_path, source)
    assert _values(returns) == {1, 2}
    assert _owners(halts) == ["UnknownCallee:h"]


def test_a_formal_callee_may_raise(tmp_path):
    source = (
        "def f(y):\n"
        "    try:\n"
        "        y()\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    return 1\n"
    )
    returns, halts = _split(tmp_path, source)
    assert _values(returns) == {1, 2}
    assert _owners(halts) == ["UnknownCallee:y"]


def test_an_unenrolled_module_function_may_raise(tmp_path):
    source = "import random\ndef f():\n    return random.random()\n"
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    term = value.to_term(owner="test")
    assert term.name == "python:call_result"
    assert term.args[0].name == "call:random.random"
    assert _owners(halts) == ["UnknownCallee:random.random"]


def test_two_calls_are_two_unknowns(tmp_path):
    returns, halts = _split(tmp_path, "def f():\n    return (h(), h())\n")
    (value,) = returns
    assert type(value) is TupleValue
    first, second = (element.to_term(owner="test") for element in value.elements)
    assert first.name == second.name == "python:call_result"
    assert first != second
    assert _owners(halts) == ["UnknownCallee:h", "UnknownCallee:h"]


def test_a_builtin_is_not_this_law(tmp_path):
    _returns, halts = _split(tmp_path, "def f():\n    return len([1])\n")
    assert not any(owner.startswith("UnknownCallee:") for owner in _owners(halts))


def test_a_source_function_is_not_this_law(tmp_path):
    source = "def g():\n    return 1\ndef f():\n    return g()\n"
    returns, halts = _split(tmp_path, source)
    assert not any(owner.startswith("UnknownCallee:") for owner in _owners(halts))


def _two_faced_and_owed(tmp_path, source):
    """The function's returns and the owners of its undetermined halts, after
    checking the call completes on one face and is owed as ``undecided``."""
    exits = _exits(tmp_path, source)
    rows = _rows(exits)
    returns = [payload for kind, payload, _guard in rows if kind == "return"]
    halts = [payload for kind, payload, _guard in rows if kind == "halt"]
    assert len(returns) == 1
    assert len(owed_calls(exits)) == 1
    return returns, _owners(halts)


def test_a_name_bound_to_a_value_is_no_builtin_and_its_call_may_raise(tmp_path):
    # #7757 (found by #8034): ``len`` rebound to ``5`` has no body the lifter
    # applies and no builtin binding; ``len('ab')`` raises ``TypeError``.  It
    # is the one unanswered call, two-faced and owed, never a completion.
    source = "def f():\n    len = 5\n    return len('ab')\n"
    _returns, owners = _two_faced_and_owed(tmp_path, source)
    assert len(owners) == 1
    assert owners[0].startswith("UnknownCallee:")


def test_a_builtin_name_a_star_import_may_rebind_is_two_faced(tmp_path):
    # ``from m import *`` may bind ``int``: the read has no builtin binding, so
    # ``int('x')`` is the one unanswered call, never a total completion.
    source = "from m import *\ndef f():\n    return int('x')\n"
    _returns, owners = _two_faced_and_owed(tmp_path, source)
    assert len(owners) == 1
    assert owners[0].startswith("UnknownCallee:")


@pytest.mark.parametrize(
    "call", ["len([1])", "isinstance(1, int)", "set([1])", "tuple([1])"]
)
def test_a_builtin_spelling_a_star_import_may_rebind_gets_no_builtin_semantics(
    tmp_path, call
):
    # #7757: the temporal floor holds ``len``/``isinstance``/``set``/``tuple``
    # by spelling, but under ``from m import *`` the callee's binding is not
    # the builtin namespace: the call is the one unanswered call, never the
    # builtin's completion.
    source = f"from m import *\ndef f():\n    return {call}\n"
    _returns, owners = _two_faced_and_owed(tmp_path, source)
    assert len(owners) == 1
    assert owners[0].startswith("UnknownCallee:")


@pytest.mark.parametrize("call", ["open(p)", "next(p)"])
def test_a_builtin_the_lifter_does_not_model_is_the_unanswered_call(tmp_path, call):
    # #7757: a callee bound to the builtin namespace with no law here (no
    # exception class, no ``type(obj)``, no total shape) runs code nothing
    # modeled; binding it to the builtin is no reason to drop its raise.
    source = f"def f(p):\n    return {call}\n"
    _returns, owners = _two_faced_and_owed(tmp_path, source)
    (owner,) = owners
    assert owner.startswith("UnknownCallee:")
    assert owner.endswith(call.split("(")[0])


@pytest.mark.parametrize("call", ["ValueError('x')", "type(p)", "str(1)"])
def test_a_builtin_a_law_answers_is_not_this_law(tmp_path, call):
    _returns, halts = _split(tmp_path, f"def f(p):\n    return {call}\n")
    assert not any(owner.startswith("UnknownCallee:") for owner in _owners(halts))


def test_an_if_on_an_unknown_call_keeps_both_suites(tmp_path):
    # The condition's completed face selects the suites; returning the
    # condition's own faces as the statement's dropped ``return 1``.
    source = "def f():\n    if h():\n        return 1\n    return 2\n"
    returns, halts = _split(tmp_path, source)
    assert _values(returns) == {1, 2}
    assert _owners(halts) == ["UnknownCallee:h"]
