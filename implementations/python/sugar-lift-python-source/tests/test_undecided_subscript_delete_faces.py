"""``del r[k]`` where nothing decides ``type(r).__delitem__`` is two-faced.

The same law as ``r[k] = v`` (#7632): the receiver is a value this frame
holds (an opaque call result, an unknown read) whose runtime type no floor,
contract or source decided, so ``__delitem__`` may run anything and raise
anything.  The delete completes only under
``python:delitem.completes(python:delitem(<occurrence>))`` and halts with an
``UndeterminedRaiseEffect`` (owner ``UndecidedDelitem``) under the
complement.  It used to refuse the whole function.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

DELETE = (
    "import shutil\n"
    "def f():\n"
    "    d = shutil.copy('a', 'b')\n"
    "    del d['k']\n"
    "{tail}"
)


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [(payload, guard) for kind, payload, guard in rows if kind == "return"]
    halts = [(payload, guard) for kind, payload, guard in rows if kind == "halt"]
    return returns, halts


def _delitem_halts(halts):
    return [
        effect
        for effect, _ in halts
        if isinstance(effect, UndeterminedRaiseEffect)
        and effect.producer_node_owner == "UndecidedDelitem"
    ]


def test_a_delete_from_an_undecided_value_completes_or_raises(tmp_path):
    returns, halts = _split(tmp_path, DELETE.format(tail="    return 1\n"))
    assert [value for value, _ in returns] == [TermValue(1)]
    assert len(_delitem_halts(halts)) == 1
    ((_value, guard),) = returns
    assert "python:delitem.completes" in str(guard)


def test_two_deletes_are_two_unknowns(tmp_path):
    returns, halts = _split(tmp_path, DELETE.format(tail="    del d['j']\n    return 1\n"))
    assert len(returns) == 1
    effects = _delitem_halts(halts)
    assert len(effects) == 2
    assert len({effect.occurrence for effect in effects}) == 2


def test_a_handler_sees_the_delete_raise(tmp_path):
    source = (
        "import shutil\n"
        "def f():\n"
        "    d = shutil.copy('a', 'b')\n"
        "    try:\n"
        "        del d['k']\n"
        "    except Exception:\n"
        "        return 2\n"
        "    return 1\n"
    )
    returns, _halts = _split(tmp_path, source)
    assert sorted(value.value for value, _ in returns) == [1, 2]
