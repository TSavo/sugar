"""A source class with no source constructor constructs: its constructor is
decided by its bases, read by binding (#7757, found by #8043).

``class E(Exception): pass`` then ``E('boom')``, or ``class P(object): pass``
then ``P()``: no class of the walk writes ``__init__`` or ``__new__``, and
every base is a source class, ``object``, or a builtin exception class whose
constructor is BaseException's ``(*args)``, each reached through its binding.
That construction is the class's constructor contract, stated under its join
symbol (``python:e.E``, #8726) and joined at prove: a call of a same-file
class is its coordinate and edge like any same-file call (#7757 steps 6 and
9; #8980), so at the call site it is owed, both faces kept, and nothing read
off the construction (an instance's ``args``, a field an ``__init__``
stores) is answered by the lift.  A base the lifter cannot read leaves the
class with no constructor contract: the call is the one unanswered call.

Every reader of a class's bases reads one walk, the MRO by binding
(``ClassDef.method_resolution_order``): ``ClassDef.constructor_is_read``,
the ``__init__`` the call runs (the first of that order,
``ClassDef.initializer_entry``) and the
constructor defaults the class value binds.  So a source ``__init__`` in a
chain ending in a builtin exception is just the first ``__init__`` found: its
frame applies, and ``super().__init__(...)`` reaches BaseException's.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import StringValue, TupleValue
from sugar_lift_py_tests.unanswered_calls import owed_calls
from sugar_source_tree.nodes import ClassDef

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


def _names(order):
    return [entry if isinstance(entry, str) else entry.name for entry in order]


def _owed_symbols(exits):
    """The join symbols of the calls ``f`` owes (``UnansweredCallV1``)."""
    return sorted(
        {
            call.symbol
            for call in owed_calls(exits)
            if getattr(call, "symbol", None) is not None
        }
    )


def test_an_exception_class_without_a_constructor_raises_its_instance(tmp_path):
    # Every face of ``f`` halts: the class call's own raise, or the raise of
    # the instance it completes with.  The call is owed under the class's
    # join symbol, where its constructor contract answers it at prove.
    source = "class E(Exception):\n    pass\ndef f():\n    raise E('boom')\n"
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert halts
    assert _owed_symbols(exits) == ["python:e.E"]


def test_the_exception_instance_is_bound_never_its_args_read_here(tmp_path):
    # ``except E as e`` binds the raised object; ``e.args`` is the one
    # undecided read on it (owed), never the ``('boom',)`` the lift once
    # read off the construction, and never a construction panic.
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
    assert "python:e.E" in _owed_symbols(exits)
    assert returns
    assert TupleValue((StringValue("boom"),)) not in returns


def test_a_documented_exception_class_constructs(tmp_path):
    source = (
        "class E(ValueError):\n"
        "    '''Raised when it is wrong.'''\n"
        "def f():\n"
        "    raise E()\n"
    )
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert halts
    assert _owed_symbols(exits) == ["python:e.E"]


def test_a_plain_class_completes_with_its_instance(tmp_path):
    for seat, bases in (("bare", ""), ("object", "(object)")):
        source = f"class P{bases}:\n    pass\ndef f():\n    return P()\n"
        exits, returns, halts = _faces(_seat(tmp_path, seat), source)
        assert len(returns) == 1
        assert _owed_symbols(exits) == ["python:e.P"]


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


def test_an_inherited_initializer_is_the_class_calls_contract(tmp_path):
    # ``B()`` runs ``A.__init__`` with its own default: that is ``B``'s
    # constructor contract, joined at prove.  The call is owed, and ``.n`` on
    # its result is never the ``'three'`` read off ``A``'s body here.
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
    assert "python:e.B" in _owed_symbols(exits)
    assert returns
    assert StringValue("three") not in returns


# -- a source ``__init__`` in a chain ending in a builtin exception ---------


EXCEPTION_WITH_INITIALIZER = (
    "class E(Exception):\n"
    "    def __init__(self, msg):\n"
    "        super().__init__('wrapped', msg)\n"
)


def test_an_exception_class_with_a_source_initializer_raises_its_instance(tmp_path):
    # The source ``__init__``'s ``super().__init__('wrapped', msg)`` reaches
    # BaseException's: the one dispatched call after ``E`` (#7757 L5), owed
    # where no namespace row states the builtin's member -- never answered
    # by the floor.  On its completed face the instance is raised.
    source = EXCEPTION_WITH_INITIALIZER + "def f():\n    raise E('boom')\n"
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert owed_calls(exits) != ()
    assert any(
        isinstance(halt, RaiseEffect)
        and halt.exception_type_coordinate.args[0].value == "source-class"
        for halt in halts
    )


def test_super_init_into_the_builtin_exception_is_not_answered_here(tmp_path):
    # ``BaseException.__init__`` seats ``args``; the lift no longer applies
    # it through ``super()`` (#7757 L5), so ``e.args`` is not read as the
    # tuple it seats: the call is owed.
    source = EXCEPTION_WITH_INITIALIZER + (
        "def f():\n"
        "    try:\n"
        "        raise E('boom')\n"
        "    except E as e:\n"
        "        return e.args\n"
    )
    exits, returns, _halts = _faces(tmp_path, source)
    assert owed_calls(exits) != ()
    assert TupleValue((StringValue("wrapped"), StringValue("boom"))) not in returns


def test_super_init_with_a_keyword_is_not_a_lift_type_error(tmp_path):
    # ``BaseException_init`` rejects every keyword actual; that is the
    # builtin's to decide, through the one dispatched call (#7757 L5), not
    # a ``TypeError`` the lift names.
    source = (
        "class E(Exception):\n"
        "    def __init__(self, msg):\n"
        "        super().__init__(msg, code=1)\n"
        "def f():\n"
        "    raise E('boom')\n"
    )
    exits, returns, halts = _faces(tmp_path, source)
    assert returns == []
    assert owed_calls(exits) != ()
    assert "TypeError" not in [
        halt.exception_name for halt in halts if isinstance(halt, RaiseEffect)
    ]


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
