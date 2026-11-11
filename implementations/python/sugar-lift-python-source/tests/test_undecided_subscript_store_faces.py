"""``r[k] = v`` where nothing decides ``type(r).__setitem__`` is two-faced.

``opts = format_options.get().copy(); opts['legacy'] = ...`` (numpy's
``get_printoptions``) stores into a value this frame holds whose runtime type
no floor, contract or source decided.  ``__setitem__`` may run anything and
raise anything, so the store completes only under
``python:setitem.completes(python:setitem(<occurrence>))`` and halts with an
``UndeterminedRaiseEffect`` (owner ``UndecidedSetitem``) under the
complement -- the #7585 law.  It used to refuse the whole function.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

STORE = (
    "import shutil\n"
    "def f():\n"
    "    d = shutil.copy('a', 'b')\n"
    "    d['k'] = 1\n"
    "{tail}"
)


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [(payload, guard) for kind, payload, guard in rows if kind == "return"]
    halts = [(payload, guard) for kind, payload, guard in rows if kind == "halt"]
    return returns, halts


def _owners(halts):
    return sorted(
        effect.producer_node_owner
        for effect, _ in halts
        if isinstance(effect, UndeterminedRaiseEffect)
    )


def test_a_store_into_an_undecided_value_completes_or_raises(tmp_path):
    returns, halts = _split(tmp_path, STORE.format(tail="    return 1\n"))
    assert [value for value, _ in returns] == [TermValue(1)]
    owners = _owners(halts)
    # The call that produced ``d`` keeps its own raise face; the store adds one.
    assert len(owners) == 2 and "UndecidedSetitem" in owners
    # The return stands only where the store completed.
    (_value, guard), = returns
    assert "python:setitem.completes" in str(guard)


def test_two_stores_are_two_unknowns(tmp_path):
    source = STORE.format(tail="    d['j'] = 2\n    return 1\n")
    returns, halts = _split(tmp_path, source)
    assert len(returns) == 1
    setitem_halts = [
        effect
        for effect, _ in halts
        if isinstance(effect, UndeterminedRaiseEffect)
        and effect.producer_node_owner == "UndecidedSetitem"
    ]
    assert len(setitem_halts) == 2
    assert len({effect.occurrence for effect in setitem_halts}) == 2


def test_a_handler_sees_the_store_raise(tmp_path):
    source = (
        "import shutil\n"
        "def f():\n"
        "    d = shutil.copy('a', 'b')\n"
        "    try:\n"
        "        d['k'] = 1\n"
        "    except Exception:\n"
        "        return 2\n"
        "    return 1\n"
    )
    returns, _halts = _split(tmp_path, source)
    assert sorted(value.value for value, _ in returns) == [1, 2]
