"""A source class with no source constructor constructs: its constructor is
decided by its bases, read by binding (#7757, found by #8043).

``class E(Exception): pass`` then ``E('boom')``, or ``class P(object): pass``
then ``P()``: no class of the walk writes ``__init__`` or ``__new__``, and
every base is a source class, ``object``, or a builtin exception class whose
constructor is BaseException's ``(*args)``, each reached through its binding.
So the call is that construction (``ClassConstructorBodySugar``, through the
class's constructor frame): it completes with the instance, and an exception
instance carries its positional actuals as ``args``.  Only a base the lifter
cannot read leaves the call the one unanswered call.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import StringValue, TupleValue
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_source_tree.nodes import ClassDef, SourceUnit

from test_assignment_evaluates_rhs import _rows
from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_undetermined_raise_except_matching import _exits
from test_unprojected_method_call_faces import _owners


def _faces(tmp_path, source):
    exits = _exits(tmp_path, source)
    rows = _rows(exits)
    returns = [payload for kind, payload, _guard in rows if kind == "return"]
    halts = [payload for kind, payload, _guard in rows if kind == "halt"]
    return exits, returns, halts


def _seat(tmp_path, name):
    seat = tmp_path / name
    seat.mkdir()
    return seat


def _admitted(tmp_path, source, name):
    source_file = _open(_corpus(tmp_path, source))
    (definition,) = [
        node
        for node in source_file.nodes()
        if isinstance(node, ClassDef) and node.name == name
    ]
    return SourceUnit.source_class_admits_source_constructor_frame(definition)


def test_an_exception_class_without_a_constructor_raises_its_instance(tmp_path):
    source = "class E(Exception):\n    pass\ndef f():\n    raise E('boom')\n"
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert owed_calls(exits) == ()
    assert _owners(halts) == []
    (raised,) = halts
    assert isinstance(raised, RaiseEffect)
    assert raised.exception_type_coordinate.args[0].value == "source-class"


def test_the_exception_instance_carries_its_args(tmp_path):
    source = (
        "class E(Exception):\n"
        "    pass\n"
        "def f():\n"
        "    try:\n"
        "        raise E('boom')\n"
        "    except E as e:\n"
        "        return e.args\n"
    )
    exits, returns, halts = _faces(tmp_path, source)
    assert owed_calls(exits) == ()
    assert returns == [TupleValue((StringValue("boom"),))]


def test_a_documented_exception_class_constructs(tmp_path):
    source = (
        "class E(ValueError):\n"
        "    '''Raised when it is wrong.'''\n"
        "def f():\n"
        "    raise E()\n"
    )
    exits, _returns, halts = _faces(tmp_path, source)
    assert owed_calls(exits) == ()
    assert not any(isinstance(halt, UndeterminedRaiseEffect) for halt in halts)


def test_a_plain_class_completes_with_its_instance(tmp_path):
    for seat, bases in (("bare", ""), ("object", "(object)")):
        source = f"class P{bases}:\n    pass\ndef f():\n    return P()\n"
        exits, returns, halts = _faces(_seat(tmp_path, seat), source)
        assert len(returns) == 1
        assert owed_calls(exits) == ()
        assert _owners(halts) == []


def test_a_base_the_lifter_cannot_read_stays_the_unanswered_call(tmp_path):
    source = (
        "from m import Base\n"
        "class E(Base):\n"
        "    pass\n"
        "def f():\n"
        "    return E(1)\n"
    )
    exits, returns, halts = _faces(tmp_path, source)
    assert len(returns) == 1
    assert len(owed_calls(exits)) == 1
    assert _owners(halts) == ["UnknownCallee:E"]


def test_bases_are_read_by_binding_never_spelling(tmp_path):
    shadowed = "Exception = make()\nclass E(Exception):\n    pass\n"
    assert _admitted(_seat(tmp_path, "shadowed"), shadowed, "E") is False
    builtin = "class E(KeyError):\n    pass\n"
    assert _admitted(_seat(tmp_path, "builtin"), builtin, "E") is True
    plain = "class P(object):\n    pass\n"
    assert _admitted(_seat(tmp_path, "object"), plain, "P") is True
    chained = "class A(Exception):\n    pass\nclass B(A):\n    pass\n"
    assert _admitted(_seat(tmp_path, "chained"), chained, "B") is True


def test_a_builtin_exception_with_its_own_signature_is_not_admitted(tmp_path):
    # ``UnicodeDecodeError()`` raises TypeError: its constructor is not
    # BaseException's ``(*args)``, so the subclass's call is not decided here.
    source = "class E(UnicodeDecodeError):\n    pass\n"
    assert _admitted(tmp_path, source, "E") is False


def test_an_assigned_constructor_is_not_admitted(tmp_path):
    source = "def make(self):\n    pass\nclass E(Exception):\n    __init__ = make\n"
    assert _admitted(tmp_path, source, "E") is False
