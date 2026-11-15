"""A class call carries its constructor's halts to its caller at prove
(#7756, #7757 step 6).

``Cls(x)`` is a call: its coordinate and an edge to the class's join symbol
(``python:<module>.<Class>``), joined at prove to the class's constructor
contract (``tree_enumerate.class_universe_outcome``) as a call of a ``def``
is (the owner's ruling of 2026-11-15, "Edge, join at prove").  The reduction
never applies the constructor's body: a class call is the two faces of the
one unanswered call, and a halt of the initializer -- including one from a
method the initializer calls, itself an edge joined in turn -- reaches the
caller through the join (#8690).

Solver twins: the lying source makes the constructor raise, so the assertion
after the class call is never reached (``unsat``: a certain halt in a callee
refutes the lie).  Where the raise is in a method ``__init__`` calls on
``self`` (``self.check(n)``), the class's constructor contract states that
call as the one dispatched edge over the instance it constructs (#7757 step
8, #8799: ``call:dispatch:check(<instance>, n, py.class("0",
python:instance(<Box>, "n")))``), and its halt as a panic locus guarded by
that call's completes atom over its ``python:call_result`` term (#8753).
Prove joins ``Box(n)`` to the class's contract, then, in turn, the dispatched
call that contract's halt guard reads (resolved on ``Box::namespace`` to
``Box.check``, #8750), whose own halt guard is ``true`` (always raises) or
``n > 5`` at the bound actual: ``check``'s call does not complete, so
``Box(n)`` does not (#8762), and the assertion after it is refuted.  The
truthful source's claim reads ``box.n``, a field of a call's result: the read names the instance as its construction left it
(``python:after(<call result>, "out")``), and the class's contract states
that field's value and that a read of it completes (#7757 step 7), so the
join decides it at prove: ``sat``.  Between step 6 and step 7 it was
``open``; before step 6 it was decided ``sat`` at the reduction by following
``Box.__init__``'s body.  The whole source may still owe members of the
methods' own proofs (``self.check(n)`` in ``__init__``'s own row), so the
truthful half is read on the test function's claims
(``witness_harness.claim_verdict``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _pair(
    tmp_path: Path, name: str, truthful: str, lying: str, *, lie: str = "unsat"
) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie_result = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(
        json.dumps(
            {"truthful": t.verdict, "lying": lie_result.verdict}, sort_keys=True
        )
    )
    # The test function is the one ``def test_`` line; every method above it.
    (test_line,) = (
        number
        for number, line in enumerate(truthful.splitlines(), start=1)
        if line.startswith("def test_")
    )
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie_result.verdict == lie


# The constructor's halt below comes from ``self.check(n)``.  Measured
# ``open`` on main scorecard 43738710481 (``38c87e62a``), when the edge's
# completes atom named the bare callee (``unknown_callee_call("<m>.check",
# <occurrence>)``), which no join reads, and nothing stated that a joined call
# completes exactly where none of its halts holds.  #8753 states the atom over
# the call's ``python:call_result`` term (which the join reads in turn), #8762
# states the completion fact, and #8799 makes the call the one dispatched
# edge prove resolves on ``Box::namespace``: the lie is refuted again,
# ``unsat``.  Never ``sat`` for the lie.


_CONSTRUCTOR = """\
class Box:
    def __init__(self, n):
        self.n = n
        self.state = self.check(n)

    def check(self, n):
{body}


def test_box():
    box = Box({actual})
    assert box.n == {actual}
"""

_ALWAYS = "        raise ValueError('bad box')"
_PLAIN = "        return n"
_ONE_FACE = "        if n > 5:\n            raise ValueError('too big')\n        return n"


def test_constructor_halt_reaches_the_class_call(tmp_path: Path) -> None:
    """``Box(3)``: the initializer's ``self.check`` completes vs always raises."""

    _pair(
        tmp_path,
        "constructor-always",
        _CONSTRUCTOR.format(body=_PLAIN, actual=3),
        _CONSTRUCTOR.format(body=_ALWAYS, actual=3),
    )


def test_constructor_halt_on_one_face_reaches_the_class_call(tmp_path: Path) -> None:
    """``Box(n)`` raising for ``n > 5``: the actual selects the face."""

    _pair(
        tmp_path,
        "constructor-one-face",
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=3),
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=9),
    )


_FIELD = """\
class Box:
    def __init__(self, n):
        self.n = n


def test_box():
    assert Box({actual}).n == 3
"""


def test_field_of_a_class_call_result_is_joined_at_prove(tmp_path: Path) -> None:
    """``Box(3).n``: the class's contract states the field the construction
    set and that its read completes (#7757 step 7)."""
    t = run_source_through_real_solver(
        tmp_path / "field-truthful", _FIELD.format(actual=3)
    )
    lie = run_source_through_real_solver(tmp_path / "field-lying", _FIELD.format(actual=4))
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    # ``__init__``'s own row stores on a formal with no actual and may owe
    # it: the truthful half is read on the test function's claims.
    test_line = _FIELD.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_CHANGED = """\
class Box:
    def __init__(self, n):
        self.n = n


def poke(b):
    b.n = 9


def test_box():
    box = Box(3)
{change}
    assert box.n == {expected}
"""


@pytest.mark.parametrize(
    "change",
    ["    box.n = 9", "    del box.n\n    box.n = 9"],
    ids=["stored", "deleted-then-stored"],
)
def test_a_changed_instance_is_not_its_constructed_state(
    tmp_path: Path, change: str
) -> None:
    """After code may have changed the instance -- a store or a delete on
    it -- the caller holds another value, never the state the class's
    contract states (#7757 step 7): the lie that reads the constructed field
    is never ``sat``, and nothing decides the truth here."""
    t = run_source_through_real_solver(
        tmp_path / "changed-truthful", _CHANGED.format(change=change, expected=9)
    )
    lie = run_source_through_real_solver(
        tmp_path / "changed-lying", _CHANGED.format(change=change, expected=3)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict != "unsat"
    assert lie.verdict != "sat"


def test_a_field_a_callee_stores_on_the_instance_is_joined_at_prove(
    tmp_path: Path,
) -> None:
    """``poke(box)``, ``poke`` storing ``b.n = 9`` (``[handed-to-a-call]``):
    ``poke``'s contract takes the class of ``b`` as its ``class:b`` input and
    states ``python:plain_store(class:b, "n") -> attr:n(python:after(out,
    "b")) == 9`` and that a read of it completes; the store itself completes
    where the guard holds (#7757 step 7).  The caller supplies the class of
    ``Box(3)``'s result (``python:constructed``, #8848) and reads ``box``
    after the call as ``python:after(<call>, "b")`` (#8796); prove decides
    the guard on ``Box``'s namespace row (no ``__setattr__``, no data
    descriptor ``n``, order ``Box, object``).  Truthful ``sat``, the lie
    that reads the constructed field ``unsat``."""
    change = "    poke(box)"
    t = run_source_through_real_solver(
        tmp_path / "handed-truthful", _CHANGED.format(change=change, expected=9)
    )
    lie = run_source_through_real_solver(
        tmp_path / "handed-lying", _CHANGED.format(change=change, expected=3)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = _CHANGED.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_FILLED = """\
class Box:
    pass


def fill(b, v):
    b.n = v
    b.m = 2


def test_box():
    box = Box()
    fill(box, 7)
    assert box.n == {expected}
"""


def test_fields_a_callee_stores_from_its_parameters_are_joined_at_prove(
    tmp_path: Path,
) -> None:
    """``fill(box, 7)`` storing ``b.n = v`` and ``b.m = 2`` on a bare
    instance: nothing after either store may change it, the guard is both
    ``plain_store`` atoms, and ``n`` is stated as the formal ``v``, bound to
    the caller's ``7`` (#7757 step 7).  Truthful ``sat``, lying ``unsat``."""
    t = run_source_through_real_solver(
        tmp_path / "filled-truthful", _FILLED.format(expected=7)
    )
    lie = run_source_through_real_solver(
        tmp_path / "filled-lying", _FILLED.format(expected=8)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = _FILLED.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_STORED_BEFORE_CODE = """\
class Box:
    pass


def note():
    return 1


def fill(b, v):
    if v > 9:
        return None
    held = v
    b.n = held
    note()


def test_box():
    box = Box()
    fill(box, 7)
    assert box.n == {expected}
"""


def test_a_field_stored_before_code_that_reaches_no_object_is_joined_at_prove(
    tmp_path: Path,
) -> None:
    """``fill(box, 7)``: ``b.n = held`` comes after an early ``return`` and
    before ``note()``, a source function that runs no code, and its value
    is a local -- none of it in a quiet tail.  The store is the last of
    ``n`` at the top level and nothing after it may change it, so the arm
    that ran to the end states the value it stored, read through the
    store's key in the context it left (``v``, bound to the caller's ``7``),
    under the plain-store guard (#7757 step 7).  Truthful ``sat``, lying
    ``unsat``."""
    t = run_source_through_real_solver(
        tmp_path / "before-code-truthful", _STORED_BEFORE_CODE.format(expected=7)
    )
    lie = run_source_through_real_solver(
        tmp_path / "before-code-lying", _STORED_BEFORE_CODE.format(expected=8)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = _STORED_BEFORE_CODE.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_TOUCHED_AFTER = """\
class Box:
    def poke(self):
        self.n = 9


def fill(b, v, other):
    b.n = v
    other.poke()


def test_box():
    box = Box()
    fill(box, 7, box)
    assert box.n == {expected}
"""


def test_a_field_a_later_call_may_change_is_never_stated(tmp_path: Path) -> None:
    """``fill(box, 7, box)``: ``b.n = 7``, then ``other.poke()`` on the same
    object stores ``n = 9``.  A method call after the store may change the
    field (another parameter may hold the same object), so ``fill`` states
    nothing of ``n`` (#7757 step 7): the lie ``box.n == 7`` is never
    ``sat``, and the truth is never ``unsat``."""
    t = run_source_through_real_solver(
        tmp_path / "touched-after-truthful", _TOUCHED_AFTER.format(expected=9)
    )
    lie = run_source_through_real_solver(
        tmp_path / "touched-after-lying", _TOUCHED_AFTER.format(expected=7)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict != "unsat"
    assert lie.verdict != "sat"


_DISPATCHED_STORE = """\
class Box:
    def set(self, v):
        self.n = v


def test_box():
    obj = Box()
    obj.set(5)
    assert obj.n == {expected}
"""


def test_a_field_a_dispatched_method_stores_on_its_receiver_is_joined_at_prove(
    tmp_path: Path,
) -> None:
    """``obj.set(5)`` on a bare ``Box()``: the call is the dispatched edge
    (``py.class("0", python:constructed(<Box>))``), and the caller reads
    ``obj`` after it by the receiver's argument key, ``python:after(<call>,
    "0")`` (``receiver_dispatch.receiver_after_dispatch``).  ``Box.set``'s
    contract states ``python:plain_store(class:self, "n") -> attr:n(
    python:after(out, "self")) == v``; prove's one binder pairs the key
    ``"0"`` with ``self``, the parameter that argument binds
    (``consistency::argument_key_aliases``), and decides the guard on
    ``Box``'s namespace row (#7757 step 7).  Truthful ``sat``, lying
    ``unsat``."""
    t = run_source_through_real_solver(
        tmp_path / "dispatched-store-truthful", _DISPATCHED_STORE.format(expected=5)
    )
    lie = run_source_through_real_solver(
        tmp_path / "dispatched-store-lying", _DISPATCHED_STORE.format(expected=6)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = _DISPATCHED_STORE.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_SUPER_STORE = """\
class Base:
    def fill(self, v):
        self.n = v


class Child(Base):
    def __init__(self):
        super().fill(5)
        assert self.n == {expected}


def test_child():
    Child()
"""


def test_a_field_a_base_method_stores_through_super_is_read_by_the_receivers_key(
    tmp_path: Path,
) -> None:
    """``super().fill(5)`` in ``Child.__init__``: in the class's constructor
    contract the receiver is the instance the construction allocated, so the
    call is the edge to ``Base.fill`` with the receiver passed implicitly as
    its first positional actual (``py.class("0", python:instance(<Child>))``).
    The constructor reads ``self`` after it as ``python:after(<call>, "0")``,
    as after a dispatched call (``receiver_dispatch.receiver_after_dispatch``),
    and prove pairs the key with ``fill``'s ``self`` (#7757 step 7).

    The ``assert self.n == 6`` is a claim of ``__init__``'s own row only:
    the class row states none of its constructor's assertions
    (``tree_enumerate.class_contract_rows``, ``definition=None``), and in
    ``__init__``'s own proof the receiver arrived by binding, so its
    ``super().fill`` is unanswered (and since #8895 joined to no contract by
    site alone).  Neither half is decided: the truth is never ``unsat`` and
    the lie never ``sat``.  Refuting the lie needs the class row to state
    the assertions its constructor runs on the allocated receiver, listed
    on #7661."""
    t = run_source_through_real_solver(
        tmp_path / "super-store-truthful", _SUPER_STORE.format(expected=5)
    )
    lie = run_source_through_real_solver(
        tmp_path / "super-store-lying", _SUPER_STORE.format(expected=6)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict != "unsat"
    assert lie.verdict != "sat"


_PROPERTY_STORE = """\
class Box:
    @property
    def n(self):
        return 5

    @n.setter
    def n(self, value):
        pass


def poke(b):
    b.n = 9


def test_box():
    box = Box()
    poke(box)
    assert box.n == {expected}
"""


def test_a_store_through_a_data_descriptor_is_never_stated_as_the_field(
    tmp_path: Path,
) -> None:
    """``b.n = 9`` where ``Box`` binds a property ``n`` whose setter drops
    the value: the store is not the plain ``__dict__`` store, so prove leaves
    ``python:plain_store(class:b, "n")`` undecided and nothing is concluded
    from ``poke``'s guarded field (#7757 step 7).  The claim ``box.n == 9``
    (false in Python: the getter returns 5) is never ``sat``."""
    lie = run_source_through_real_solver(
        tmp_path / "property-lying", _PROPERTY_STORE.format(expected=9)
    )
    print(json.dumps({"lying": lie.verdict}, sort_keys=True))
    assert lie.verdict != "sat"


# ---------------------------------------------------------------------------
# The same sources in process (a unit check, not a twin).  The class call is
# the edge's two faces whatever the constructor does: its halt is decided at
# prove, never at the reduction.
# ---------------------------------------------------------------------------


def _test_function_outcome(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


def _decided_raises(outcome) -> list:
    """The exception names of the halted faces the reduction decided (every
    halt but the one unanswered call's undetermined raise)."""
    from sugar_lift_py_tests.outcome import Halted

    return [
        getattr(face.effect, "exception_name", None)
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
        and type(face.effect).__name__ != "UndeterminedRaiseEffect"
    ]


@pytest.mark.parametrize(
    ("body", "actual"),
    [(_PLAIN, 3), (_ALWAYS, 3), (_ONE_FACE, 3), (_ONE_FACE, 9)],
    ids=["plain", "always-raises", "one-face-not-taken", "one-face-taken"],
)
def test_constructor_halt_is_decided_at_prove(body: str, actual: int) -> None:
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    outcome = _test_function_outcome(_CONSTRUCTOR.format(body=body, actual=actual))
    assert isinstance(outcome, ExitSet), outcome
    kinds = {type(face) for face in outcome.exits}
    # The edge's two faces: it may complete, it may halt.
    assert Completed in kinds and Halted in kinds, outcome
    assert "ValueError" not in _decided_raises(outcome), outcome


_FACTORY = """\
class Box:
    def __init__(self, n):
        self.n = n
        if n > 5:
            raise ValueError('too big')

    @classmethod
    def make(cls, n):
        return cls(n)
"""


@pytest.mark.parametrize("actual", [3, 9])
def test_class_method_call_is_its_edge(actual: int) -> None:
    """``Box.make(n)``: the classmethod the lookup selected on the class is
    its coordinate and edge (#7757 step 6), whatever ``make``'s body does;
    ``__init__``'s raise reaches the caller at prove (unit check)."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (_FACTORY, "factory.py", blake3_512_of(_FACTORY.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    ctx = ReduceContext.root(owner="test")
    box = class_def.sugar().desugar(ctx).completed_value()
    outcome = box.call_method_value(
        "make", (TermValue(actual),), owner="test", blame="make-site", ctx=ctx
    )
    assert isinstance(outcome, ExitSet), outcome
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [type(face.effect).__name__ for face in halts] == ["UndeterminedRaiseEffect"]
