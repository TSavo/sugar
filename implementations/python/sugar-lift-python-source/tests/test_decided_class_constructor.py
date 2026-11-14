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

Every reader of a class's bases reads one walk, the MRO by binding
(``ClassDef.method_resolution_order``): the admission, the ``__init__`` the
call runs (the first of that order, ``ClassDef.initializer_entry``) and the
constructor defaults the class value binds.  So a source ``__init__`` in a
chain ending in a builtin exception is just the first ``__init__`` found: its
frame applies, and ``super().__init__(...)`` reaches BaseException's.
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


def _definition(tmp_path, source, name):
    source_file = _open(_corpus(tmp_path, source))
    (definition,) = [
        node
        for node in source_file.nodes()
        if isinstance(node, ClassDef) and node.name == name
    ]
    return definition


def _admitted(tmp_path, source, name):
    return SourceUnit.source_class_admits_source_constructor_frame(
        _definition(tmp_path, source, name)
    )


def _names(order):
    return [entry if isinstance(entry, str) else entry.name for entry in order]


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


def test_an_os_error_subclass_is_not_admitted(tmp_path):
    # ``OSError(2, 'x', 'f').args == (2, 'x')``: OSError's constructor drops
    # the filename actuals from ``args``, so it is not BaseException's law.
    source = "class E(FileNotFoundError):\n    pass\n"
    assert _admitted(tmp_path, source, "E") is False


# -- the one base walk (``ClassDef.method_resolution_order``) ---------------


def test_the_initializer_is_the_first_of_the_mro_read_by_binding(tmp_path):
    chained = (
        "class A:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "class B(A):\n"
        "    pass\n"
    )
    b = _definition(_seat(tmp_path, "chained"), chained, "B")
    assert _names(b.method_resolution_order()) == ["B", "A", "object"]
    assert b.initializer_entry().name == "A"
    assert b._source_initializer().name == "__init__"
    # C's MRO is C, A, Exception, BaseException, B, object: Exception's
    # ``__init__`` stands before B's, so B's never runs for ``C(...)``.
    diamond = (
        "class A(Exception):\n"
        "    pass\n"
        "class B:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "class C(A, B):\n"
        "    pass\n"
    )
    c = _definition(_seat(tmp_path, "diamond"), diamond, "C")
    assert _names(c.method_resolution_order()) == [
        "C",
        "A",
        "Exception",
        "BaseException",
        "B",
        "object",
    ]
    assert c.initializer_entry() == "Exception"
    assert c._source_initializer() is None


def test_a_local_base_is_never_the_module_class_of_its_spelling(tmp_path):
    # ``B``'s base is the class local to ``f``; the module ``A`` with an
    # ``__init__`` shares only its spelling.
    source = (
        "class A:\n"
        "    def __init__(self, x, y):\n"
        "        pass\n"
        "def f():\n"
        "    class A:\n"
        "        pass\n"
        "    class B(A):\n"
        "        pass\n"
        "    return B\n"
    )
    b = _definition(tmp_path, source, "B")
    assert b.method_resolution_order() is None
    assert b.initializer_entry() is None
    assert b._source_initializer() is None


def test_an_unread_base_leaves_the_initializer_undecided(tmp_path):
    # The first base follows the class in every MRO Python builds, but the
    # unread ``Mixin``'s metaclass or ``__init_subclass__`` may write
    # ``__init__`` on ``B`` itself: the one class-namespace lookup
    # (``namespace_owner``) does not decide it, so neither is ``A``'s assumed.
    source = (
        "from m import Mixin\n"
        "class A:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "class B(A, Mixin):\n"
        "    pass\n"
    )
    b = _definition(tmp_path, source, "B")
    assert b.method_resolution_order() is None
    assert b.initializer_entry() is None


def test_an_inherited_initializer_binds_its_own_default(tmp_path):
    source = (
        "class A:\n"
        "    def __init__(self, n='three'):\n"
        "        self.n = n\n"
        "class B(A):\n"
        "    pass\n"
        "def f():\n"
        "    return B().n\n"
    )
    exits, returns, _halts = _faces(tmp_path, source)
    assert owed_calls(exits) == ()
    assert returns == [StringValue("three")]


# -- a source ``__init__`` in a chain ending in a builtin exception ---------


EXCEPTION_WITH_INITIALIZER = (
    "class E(Exception):\n"
    "    def __init__(self, msg):\n"
    "        super().__init__('wrapped', msg)\n"
)


def test_a_source_initializer_before_a_builtin_exception_is_admitted(tmp_path):
    assert _admitted(tmp_path, EXCEPTION_WITH_INITIALIZER, "E") is True


def test_an_exception_class_with_a_source_initializer_raises_its_instance(tmp_path):
    source = EXCEPTION_WITH_INITIALIZER + "def f():\n    raise E('boom')\n"
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert owed_calls(exits) == ()
    assert _owners(halts) == []
    (raised,) = halts
    assert isinstance(raised, RaiseEffect)
    assert raised.exception_type_coordinate.args[0].value == "source-class"


def test_super_init_into_the_builtin_exception_seats_args(tmp_path):
    source = EXCEPTION_WITH_INITIALIZER + (
        "def f():\n"
        "    try:\n"
        "        raise E('boom')\n"
        "    except E as e:\n"
        "        return e.args\n"
    )
    exits, returns, _halts = _faces(tmp_path, source)
    assert owed_calls(exits) == ()
    assert returns == [TupleValue((StringValue("wrapped"), StringValue("boom")))]


def test_super_init_with_a_keyword_is_the_type_error(tmp_path):
    # ``BaseException_init`` rejects every keyword actual.
    source = (
        "class E(Exception):\n"
        "    def __init__(self, msg):\n"
        "        super().__init__(msg, code=1)\n"
        "def f():\n"
        "    raise E('boom')\n"
    )
    _exits_, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert [
        halt.exception_name for halt in halts if isinstance(halt, RaiseEffect)
    ] == ["TypeError"]


# -- the inherited-exception frame reads the one base walk ------------------


def test_the_inherited_exception_frame_is_the_first_initializer_of_the_mro(tmp_path):
    # C's MRO is C, B, A, Exception, BaseException, object: B's source
    # ``__init__`` runs, though a base is an exception class.
    source_first = (
        "class A(Exception):\n"
        "    pass\n"
        "class B:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "class C(B, A):\n"
        "    pass\n"
    )
    c = _definition(_seat(tmp_path, "source-first"), source_first, "C")
    assert c.initializer_entry().name == "B"
    assert c._inherits_default_exception_constructor() is False
    # C's MRO is C, A, Exception, BaseException, B, object: Exception's.
    exception_first = (
        "class A(Exception):\n"
        "    pass\n"
        "class B:\n"
        "    def __init__(self, x):\n"
        "        pass\n"
        "class C(A, B):\n"
        "    pass\n"
    )
    c = _definition(_seat(tmp_path, "exception-first"), exception_first, "C")
    assert c._inherits_default_exception_constructor() is True


def test_an_unread_order_inherits_no_exception_frame(tmp_path):
    source = "from m import Mixin\nclass E(Exception, Mixin):\n    pass\n"
    e = _definition(tmp_path, source, "E")
    assert e.method_resolution_order() is None
    assert e.construction_order() is None
    assert e._inherits_default_exception_constructor() is False


def test_an_os_error_subclass_inherits_no_exception_frame(tmp_path):
    # ``OSError(2, 'x', 'f').args == (2, 'x')``: the ``(*args)`` frame would
    # store every positional actual.
    for seat, base in (("os", "FileNotFoundError"), ("syntax", "SyntaxError")):
        source = f"class E({base}):\n    pass\n"
        e = _definition(_seat(tmp_path, seat), source, "E")
        assert _names(e.method_resolution_order())[:2] == ["E", base]
        assert e.construction_order() is None
        assert e._inherits_default_exception_constructor() is False


# -- a class called as a value with an unread constructor -------------------


def test_a_class_value_call_with_an_unread_base_is_the_unanswered_call(tmp_path):
    # ``E()`` with no actuals is applied through the class value
    # (``ClassDefinitionValue.callable_application_with``): never the empty
    # ``object`` frame for a class whose bases are not read.
    source = (
        "from m import Base\n"
        "class E(Base):\n"
        "    pass\n"
        "def f():\n"
        "    return E()\n"
    )
    exits, returns, halts = _faces(tmp_path, source)
    assert len(returns) == 1
    assert len(owed_calls(exits)) == 1
    assert _owners(halts) == ["UnknownCallee:E"]


def test_a_class_value_call_of_an_os_error_subclass_is_the_unanswered_call(tmp_path):
    source = "class E(FileNotFoundError):\n    pass\ndef f():\n    return E()\n"
    exits, returns, halts = _faces(tmp_path, source)
    assert len(returns) == 1
    assert len(owed_calls(exits)) == 1
    assert _owners(halts) == ["UnknownCallee:E"]
