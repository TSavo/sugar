"""A method call applies its body through the one application routine (#7756).

Superseded by #7757 step 6 (the owner's ruling of 2026-11-15, "Edge, join at
prove"): a class call is its coordinate and an edge, so every receiver below
(``box = Box()``) is a call's result, and a method of it is not dispatched at
the reduction; a method call on a receiver whose class is decided is an edge
to the method's join symbol.  The twins below now state that: ``open`` on
both halves, and the in-process checks read the undecided faces.  #7757 step
8 dispatches a method of a class call's result at prove where the result is a
bare instance (no source ``__init__``/``__new__`` runs): ``one-branch`` is
decided again.  What follows is the rule as it stood before.

A plain call ``f(...)`` runs ``f``'s body through ``CallSiteValue.producer_outcome``
and carries every face of it: completions and raises.  A bound method call
``obj.m(...)`` is the same application with the receiver bound as the first
actual (``object_value.apply_bound_method``), so a method that raises leaves its
caller raising.

Each pair differs in exactly one thing and goes through the real solver.  The
lying source makes the method raise on the path taken, so the assertion after
the call is never reached (``unsat``).

The receiver of every call whose raise a twin is about is made in the frame
that calls the method (``box = Box()``): its fields are current there
(``object_identity.contents_current``, the one currency rule), so the lookup
selects the class's method and its body is applied.  Currency belongs to the
object, never to how it was reached: inside the applied body, ``self`` is the
caller's actual with the caller's currency, so ``self.n`` and ``self.check()``
read the same object the caller holds (#7757).  Every truthful claim is
decided (``sat``).

Only a method's own proof -- no caller, no actual -- reads ``self`` with its
state unknown at entry: there a raise selected through ``self`` is decided in
neither half (#8151, #8153), asserted in process below.  What such a proof
owes (``return self.n`` in ``read``'s own proof) is an ``undecided`` member of
the source, and a source that owes anything is never ``sat`` as a whole
(step 8).  So the truthful half is read on the test function's own claims
(``witness_harness.claim_verdict``): every member a method's own proof owes
sits above the test function and is set aside; the test function's claim, and
anything the test function itself owed, is read as ``prove_verdict`` reads it.
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
    tmp_path: Path,
    name: str,
    truthful: str,
    lying: str,
    expected: tuple[str, str] = ("open", "open"),
) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    # The test function is the one ``def test_`` line; every method above it.
    (test_line,) = (
        number
        for number, line in enumerate(truthful.splitlines(), start=1)
        if line.startswith("def test_")
    )
    # #7757 step 6: the receiver is a class call's result (its coordinate and
    # edge, no instance built at the reduction), so the method's dispatch is
    # not decided at the reduction.  #7757 step 8: it is decided at prove
    # where the class call's result is an instance of the class
    # (``type.__call__`` with a builtin ``__new__``,
    # ``CallSiteValue.instance_of``), over the class and fields its contract
    # states, and the claim reads what the method's contract states:
    # ``expected``.  A method reading ``self.<field>`` reads a field of an
    # instance that arrived by binding: such a truthful half stays ``open``,
    # never ``sat`` for the lie, listed on #7661.
    truthful_verdict, lying_verdict = expected
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == truthful_verdict
    assert lie.verdict == lying_verdict


_OBJ_CALL = """\
class Gauge:
    def __init__(self, n):
        self.n = n

    def read(self):
{body}


def test_gauge():
    gauge = Gauge(4)
    value = gauge.read()
    assert value == 4
"""


def test_receiver_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``obj.m()``: ``m`` completes vs ``m`` always raises.

    ``Gauge(4)`` runs a source ``__init__``, and its result is still an
    instance of ``Gauge`` (``type.__call__`` with ``object.__new__``):
    ``gauge.read()`` is dispatched at prove over the class and fields
    ``Gauge``'s contract states (``python:constructed``, #7757 step 8).  The
    lying ``read`` always raises, so the claim after it is refuted:
    ``unsat``.  The truthful ``read`` returns ``self.n``: in ``read``'s own
    proof that is the ``field:self.n`` input under ``python:plain_read(
    class:self, "n")`` (#7757), and the dispatched call binds it to the
    value ``Gauge``'s constructor contract states for ``n`` on every
    completed face (``attr:n(python:after(<Gauge(4)>, "out"))``, 4), with
    the guard decided on ``Gauge``'s namespace row: ``sat``."""

    _pair(
        tmp_path,
        "obj-call",
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
        expected=("sat", "unsat"),
    )


# A method calls a method of its class on a receiver made in its own frame:
# the inner method's raise is carried out through the outer method to the
# test function.  The same call through the caller's ``self``
# (``self.check()``) is ``_ARRIVED_SELF_CALL`` below.
_SELF_CALL = """\
class Box:
    def run(self):
        inner = Box()
        state = inner.check()
        return 3

    def check(self):
{body}


def test_box():
    box = Box()
    value = box.run()
    assert value == 3
"""


def test_self_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """A method call inside a method: ``m`` completes vs ``m`` always raises.

    ``Box()`` runs no source code, so ``box`` and ``inner`` are bare ``Box``
    instances: ``box.run()`` is dispatched at prove on ``Box``'s namespace to
    ``Box.run``, and inside ``run``'s contract ``inner.check()`` is the one
    dispatched edge to ``Box.check`` (#7757 step 8).  ``check``'s contract
    states its completion (``return None``) or its halt (always raises), and
    the completion fact carries it through ``run`` to the test function's
    claim.  Decided: truthful ``sat`` (scorecard run 43745139407 measured the
    test function's claim ``sat``), lying ``unsat`` (measured ``unsat``)."""

    _pair(
        tmp_path,
        "self-call",
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
        expected=("sat", "unsat"),
    )


# The test function applies the method on a receiver it made, and the actual
# selects the arm: the truthful actual takes the completing branch, the lying
# one the raising branch.
_ONE_BRANCH = """\
class Limit:
    def check(self, n):
        if n > 5:
            raise ValueError('too big')
        return n


def test_limit():
    limit = Limit()
    value = limit.check(n={actual})
    assert value == {actual}
"""


def test_method_raising_on_one_branch_carries_that_raise(tmp_path: Path) -> None:
    """``obj.m(n=...)`` raising on one branch: the actual selects the arm.

    ``Limit()`` runs no source code, so ``limit`` is a bare ``Limit``:
    ``limit.check(n=...)`` is dispatched at prove on ``Limit``'s namespace to
    ``Limit.check``, whose contract states the raise under ``n > 5`` (#7757
    step 8).  Decided again: truthful ``sat``, lying ``unsat``."""

    _pair(
        tmp_path,
        "one-branch",
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
        expected=("sat", "unsat"),
    )


# The same branch through a ``staticmethod`` and a ``classmethod`` read off
# the bare instance: the dispatch binds each as its descriptor binds it at
# prove (#7757 step 8, the kind the class's namespace row states) -- the
# instance not passed, or the class passed in its place -- and the actual
# selects the arm.
_DESCRIPTOR_BRANCH = """\
class Limit:
    @{decorator}
    def check({formals}):
        if n > 5:
            raise ValueError('too big')
        return n


def test_limit():
    limit = Limit()
    value = limit.check(n={actual})
    assert value == {actual}
"""


@pytest.mark.parametrize(
    ("decorator", "formals"),
    [("staticmethod", "n"), ("classmethod", "cls, n")],
)
def test_a_descriptor_method_on_a_bare_instance_is_dispatched_by_its_kind(
    tmp_path: Path, decorator: str, formals: str
) -> None:
    """``limit.check(n=...)`` where ``check`` is a ``staticmethod`` or a
    ``classmethod``: dispatched at prove on ``Limit``'s namespace, which
    states the kind, and bound as Python binds it read off an instance.
    Before, prove dispatched only plain functions and the lift chose the
    method itself.  Truthful ``sat``, lying ``unsat``."""

    _pair(
        tmp_path,
        f"{decorator}-branch",
        _DESCRIPTOR_BRANCH.format(decorator=decorator, formals=formals, actual=3),
        _DESCRIPTOR_BRANCH.format(decorator=decorator, formals=formals, actual=9),
        expected=("sat", "unsat"),
    )


# A ``*args`` method on the bare instance: the dispatched call passes its
# actuals as Python spells them (``check(limit, 3, 9)``), and prove's one
# binder binds ``*parts`` to the tuple of the positional actuals no other
# parameter takes (#7757, the contract's ``variadicFormals``).  Before, the
# call did not fit the contract's two formals and stayed owed.
_STAR_ARGS_CALL = """\
class Limit:
    def check(self, *parts):
{body}


def test_limit():
    limit = Limit()
    value = limit.check(3, 9)
    assert value == 3
"""


def test_a_star_args_method_on_a_bare_instance_binds_its_actuals(
    tmp_path: Path,
) -> None:
    """``limit.check(3, 9)`` with ``def check(self, *parts)``: completes
    with 3 vs always raises.  Truthful ``sat``, lying ``unsat``."""

    _pair(
        tmp_path,
        "star-args-call",
        _STAR_ARGS_CALL.format(body="        return 3"),
        _STAR_ARGS_CALL.format(body="        raise ValueError('too many')"),
        expected=("sat", "unsat"),
    )


# A keyword naming the ``*args`` formal never binds it: Python puts it in
# ``**kwargs``, or raises ``TypeError`` where nothing collects it.  The edge
# of a same-file definition supplies a packed variadic as ``py.packed``, so
# prove's one binder reads every ``py.kwarg`` as the keyword it is (#7757).
# Before, a ``py.kwarg`` naming the variadic bound it as it stood:
# ``limit.check(rest=3)`` against ``def check(self, *rest)`` fit, ``check``
# completed with 3, and the claim after a call Python refuses read ``sat``;
# against ``def check(self, *rest, **kw)`` returning ``rest``, ``rest`` was
# ``3`` where Python makes it ``()``.
_KEYWORD_NAMING_STAR = """\
class Limit:
    def check(self, *rest{kw}):
        return {returned}


def test_limit():
    limit = Limit()
    value = limit.check({actuals})
    assert value == 3
"""


def test_a_keyword_naming_the_star_formal_never_binds_it(tmp_path: Path) -> None:
    """Truthful: ``limit.check(3)`` with ``def check(self, *rest)`` returning
    3: ``sat``.  Lying: ``limit.check(rest=3)``, which Python refuses
    (``TypeError``: no ``**kwargs`` collects ``rest``), and
    ``limit.check(rest=3)`` against ``def check(self, *rest, **kw)``
    returning ``rest`` (Python binds ``rest`` to ``()``): neither is
    ``sat``.  The refused call stays owed at prove (the binder states the
    misfit; the ``TypeError`` halt face is kept, never dropped)."""
    truthful = _KEYWORD_NAMING_STAR.format(kw="", returned="3", actuals="3")
    refused = _KEYWORD_NAMING_STAR.format(kw="", returned="3", actuals="rest=3")
    collected = _KEYWORD_NAMING_STAR.format(
        kw=", **kw", returned="rest", actuals="rest=3"
    )
    t = run_source_through_real_solver(tmp_path / "keyword-star-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / "keyword-star-refused", refused)
    kept = run_source_through_real_solver(tmp_path / "keyword-star-kwargs", collected)
    print(
        json.dumps(
            {"truthful": t.verdict, "refused": lie.verdict, "kwargs": kept.verdict},
            sort_keys=True,
        )
    )
    test_line = truthful.splitlines().index("def test_limit():") + 1
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict != "sat"
    assert kept.verdict != "sat"


# The test function spreads a dict it made into the method applied on a
# receiver it made.
_SPREAD_CALL = """\
class Store:
    def open(self, mode='r'):
{body}


def test_store():
    store = Store()
    options = {{'mode': 'r'}}
    value = store.open(**options)
    assert value == 'r'
"""


def test_spread_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``obj.m(**kwargs)``: the method completes vs always raises."""

    _pair(
        tmp_path,
        "spread-call",
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
    )


# The three twins above with the raising method selected through the method's
# own ``self``.  Applied from the test function, ``self`` is the receiver the
# test function made, current there and so in the body: the call is decided
# (``test_a_method_selected_through_the_callers_self_is_decided_in_process``).
# In ``run``'s own proof ``self`` has no actual: the call is decided in
# neither half
# (``test_a_method_selected_through_an_arrived_self_is_undecided_in_process``).
_ARRIVED_SELF_CALL = """\
class Box:
    def __init__(self, n):
        self.n = n

    def run(self):
        state = self.check()
        return self.n

    def check(self):
{body}


def test_box():
    box = Box(3)
    value = box.run()
    assert value == 3
"""


_ARRIVED_ONE_BRANCH = """\
class Limit:
    def __init__(self, n):
        self.n = n

    def run(self, n):
        state = self.check(n=n)
        return state

    def check(self, n):
        if n > 5:
            raise ValueError('too big')
        return n


def test_limit():
    limit = Limit(0)
    value = limit.run({actual})
    assert value == {actual}
"""


_ARRIVED_SPREAD_CALL = """\
class Store:
    def __init__(self):
        self.mode = 'r'

    def run(self, **kwargs):
        handle = self.open(**kwargs)
        return 1

    def open(self, mode='r'):
{body}


def test_store():
    store = Store()
    value = store.run(mode='r')
    assert value == 1
"""


_SUPER_CALL = """\
class Base:
    def check(self):
{body}


class Child(Base):
    def __init__(self, n):
        self.n = n

    def run(self):
        state = super().check()
        return self.n


def test_child():
    child = Child(2)
    value = child.run()
    assert value == 2
"""


def test_super_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``super().m()``: the base method completes vs always raises."""

    _pair(
        tmp_path,
        "super-call",
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
    )


# A method reads a field ``__init__`` set, through ``self``, applied on a
# receiver the test function made: the caller holds ``box`` as current (made
# in its frame, nothing ran since), and the body reads the same object at the
# same moment, so ``self.n`` is the value ``__init__`` stored (#7757).  Before,
# the formal read applied ``object_identity.arrived`` at a followed call and
# the body read the caller's current object as stale: two answers for one
# object at one moment.
_FIELD_READ = """\
class Box:
    def __init__(self):
        self.n = 3

    def run(self):
        return self.n


def test_box():
    box = Box()
    value = box.run()
    assert value == {claim}
"""


def test_a_field_read_through_the_callers_self_reads_the_value(
    tmp_path: Path,
) -> None:
    """``box = Box(); box.run()``, ``run`` returning ``self.n``: the claim on
    the value ``__init__`` stored is decided, its denial refuted.  ``run``'s
    read of ``self.n`` is its ``field:self.n`` input, bound at the
    dispatched call to the value ``Box``'s constructor contract states
    (#7757): truthful ``sat``, lying ``unsat``."""

    _pair(
        tmp_path,
        "field-read",
        _FIELD_READ.format(claim=3),
        _FIELD_READ.format(claim=4),
        expected=("sat", "unsat"),
    )


# A base ``__init__`` calls ``self.setup()``; the subclass overrides
# ``setup`` and reaches the base ``__init__`` through ``super().__init__()``.
# Python runs the subclass's ``setup``.  ``Base.__init__``'s contract takes
# the class of ``self`` as its ``class:self`` input, and ``self.setup()`` there
# is the dispatched edge over it; ``Derived``'s constructor contract supplies
# ``Derived`` at its ``super().__init__()`` (#7757 step 8).  One base and one
# override raise, the other completes: the claim after ``Derived()`` holds
# only where the override runs.
_INIT_DISPATCH = """\
class Base:
    def __init__(self):
        self.setup()

    def setup(self):
{base}


class Derived(Base):
    def __init__(self):
        super().__init__()

    def setup(self):
{derived}


def test_derived():
    made = Derived()
    reached = 1
    assert reached == 1
"""

_RAISES = "        raise ValueError('ran')"
_COMPLETES = "        return None"


def test_a_base_init_dispatches_self_m_on_the_subclass_reaching_it(
    tmp_path: Path,
) -> None:
    """``Derived()`` runs ``Base.__init__`` through ``super().__init__()``,
    and ``self.setup()`` there is ``Derived.setup``.  Truthful: the base's
    ``setup`` raises and the override completes, so the claim is true only
    of ``Derived.setup``: ``sat``.  Lying: the override raises and the
    base's completes, so the claim is true only of ``Base.setup``: never
    ``sat`` (resolving ``self.setup()`` on the class that wrote the
    ``__init__`` would read it ``sat``)."""
    truthful = _INIT_DISPATCH.format(base=_RAISES, derived=_COMPLETES)
    lying = _INIT_DISPATCH.format(base=_COMPLETES, derived=_RAISES)
    t = run_source_through_real_solver(tmp_path / "init-dispatch-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / "init-dispatch-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = truthful.splitlines().index("def test_derived():") + 1
    # ``Base.__init__``'s own proof binds no class: its dispatched member is
    # owed there, so the truthful half is read on the test function's claims.
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict != "sat"


# A store to ``item.__class__`` gives the object another class
# (``object.__class__``'s setter).  The caller supplies the class it made the
# object of (``Plain``), so a dispatch over ``class:item`` would resolve
# ``item.kind()`` on ``Plain`` and read ``1`` -- the lie -- as ``sat``.  A
# ``__class__`` store makes the module dynamic (``receiver_dispatch.
# module_attribute_names``): nothing is dispatched over a class input, the call
# stays owed, and neither half is decided.
_CLASS_STORE = """\
class Plain:
    def kind(self):
        return 1


class Other:
    def kind(self):
        return 2


def morph(item):
    item.__class__ = Other
    return item.kind()


def test_morph():
    value = morph(Plain())
    assert value == {expected}
"""


def test_a_class_store_on_the_receiver_is_never_dispatched_on_the_callers_class(
    tmp_path: Path,
) -> None:
    """``morph(Plain())`` with ``item.__class__ = Other`` before
    ``item.kind()``: Python runs ``Other.kind`` (``2``).  Truthful claims
    ``2``, lying claims ``1`` (what ``Plain.kind`` returns).  Read on the
    test function's own claims (``morph``'s own proof owes its call either
    way), the lie is never ``sat``: dispatching on the class the caller
    supplied would read it ``sat``.  Not bridged: the class after the store
    is not decided here, so both halves are ``open``."""
    truthful = _CLASS_STORE.format(expected=2)
    lying = _CLASS_STORE.format(expected=1)
    t = run_source_through_real_solver(tmp_path / "class-store-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / "class-store-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    test_line = truthful.splitlines().index("def test_morph():") + 1
    lie_claim = claim_verdict(lie.prove_doc, claims_from_line=test_line)
    assert lie_claim != "sat"
    assert lie_claim == "open"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "open"


# ---------------------------------------------------------------------------
# The same pairs in process (a unit check, not a twin): the lifter's own
# outcome for the test function.  Lying carries only the method's raise;
# truthful completes alone.  Before #7756 every lying source here completed.
# ---------------------------------------------------------------------------


_IN_PROCESS_PAIRS = {
    "obj-call": (
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
        "KeyError",
    ),
    "self-call": (
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
        "ValueError",
    ),
    "one-branch": (
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
        "ValueError",
    ),
    "super-call": (
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
        "ValueError",
    ),
    "spread-call": (
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
        "OSError",
    ),
}


_ARRIVED_SELF_PAIRS = {
    "self-call": (
        _ARRIVED_SELF_CALL.format(body="        return None"),
        _ARRIVED_SELF_CALL.format(body="        raise ValueError('bad box')"),
    ),
    "one-branch": (
        _ARRIVED_ONE_BRANCH.format(actual=3),
        _ARRIVED_ONE_BRANCH.format(actual=9),
    ),
    "spread-call": (
        _ARRIVED_SPREAD_CALL.format(body="        return mode"),
        _ARRIVED_SPREAD_CALL.format(body="        raise OSError('cannot open')"),
    ),
}


def _function_outcome(source: str, name: str | None = None):
    """The lifter's own outcome for the function named ``name`` in
    ``source`` (the one ``test_`` function when ``name`` is None), reduced on
    its own: a test function, or a method's own proof (no caller, so no
    formal has an actual)."""
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
        if isinstance(node, FunctionDef)
        and (node.name == name if name is not None else node.name.startswith("test_"))
    )
    return function_universe_outcome(function)


def _test_function_outcome(source: str):
    """The outcome of the one ``test_`` function in ``source``."""
    return _function_outcome(source)


# Inside a method applied at a followed call, ``self`` is the caller's actual
# with the caller's currency (``object_identity.contents_current``): every
# receiver here is made in the test function, current there, so it is current
# in the body, and ``self.<name>`` -- a field or a method, read through
# ``ObjectValue.attribute`` -- reads the object's own member (#7757).
#
# - ``obj-call``: ``gauge.read()`` selects ``read``; the lying body's
#   ``KeyError`` reaches the caller, the truthful ``return self.n`` reads 4.
# - ``super-call``: the base method is selected through ``super()``; the lying
#   body's ``ValueError`` reaches the caller.  ``Base.check`` stores nothing on
#   ``self``, so the receiver after the call is the current one
#   (``call_site_value.receiver_after_its_call``) and ``self.n`` reads 2.
# - ``self-call``, ``one-branch``, ``spread-call``: the raising method is
#   selected on a receiver made in the calling frame, so the lying body's
#   raise reaches the caller and the truthful half completes alone.


def _undecided_faces(outcome) -> None:
    """A completed face under an undecided read's guard, and every halt an
    undetermined raise: nothing about the read is decided, no exception is
    named."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    assert outcome.completed_value() is None, outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed and halted, outcome
    for halt in halted:
        assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
        assert halt.effect.exception_name is None, halt.effect


@pytest.mark.parametrize("form", sorted(_IN_PROCESS_PAIRS))
def test_a_method_of_a_class_call_result_is_undecided_in_process(form: str) -> None:
    """#7757 step 6: the receiver is a class call's coordinate and edge, so
    the method the call names is not dispatched at the reduction and no raise
    of its body is decided there; both halves are the undecided faces.
    Before step 6 the lying half carried the method's own raise."""
    truthful, lying, _exception = _IN_PROCESS_PAIRS[form]
    _undecided_faces(_test_function_outcome(truthful))
    _undecided_faces(_test_function_outcome(lying))


def test_a_field_read_off_a_class_call_result_is_undecided_in_process() -> None:
    """``box = Box(); box.run()``: ``box`` is the class call's coordinate, so
    ``run`` is not dispatched at the reduction (#7757 step 6)."""
    _undecided_faces(_test_function_outcome(_FIELD_READ.format(claim=3)))


def test_a_method_called_through_a_class_call_result_is_undecided_in_process() -> None:
    """``box = Box(3); box.run()``, ``run`` calling ``self.check()``: the
    call of ``run`` is a method of a class call's result, not dispatched at
    the reduction (#7757 step 6); neither half decides ``check``'s raise."""
    truthful, lying = _ARRIVED_SELF_PAIRS["self-call"]
    _undecided_faces(_test_function_outcome(truthful))
    _undecided_faces(_test_function_outcome(lying))


@pytest.mark.parametrize("form", sorted(_ARRIVED_SELF_PAIRS))
def test_a_method_selected_through_an_arrived_self_is_undecided_in_process(
    form: str,
) -> None:
    """The raising method selected through ``self`` in ``run``'s own proof:
    no caller, so ``self`` has no actual and its state is unknown at entry.
    The call is decided in neither half (#8153)."""
    truthful, lying = _ARRIVED_SELF_PAIRS[form]
    _undecided_faces(_function_outcome(truthful, "run"))
    _undecided_faces(_function_outcome(lying, "run"))


# ---------------------------------------------------------------------------
# A method call on a receiver the lifter does not have is the plain call to a
# callee it does not have: two faces (#7756).  Before, it completed alone.
#
# What the rule claims, through the solver: what is asserted after the call is
# asserted on the call's completing face, and that face stands under
# ``python:unknown_callee_call.completes``, which nothing here decides.  So a
# true claim after the call is not decided (``open``): nothing proves the call
# completes.  A false claim is refuted on every face (``unsat``).  Before this
# change the call completed alone and the true claim came back ``sat``: a
# verdict for a program whose call may raise.  ``open`` is this twin stating
# "not bridged"; it is not a green truthful half, and it becomes ``sat`` only
# when something decides the call.
#
# The call's other face is a raise.  A raise is not a refutation, and the
# solver gives no verdict on it until halted arms are emitted from the
# reduction (#7766), so the raise face is shown at the reduction level below
# and no ``unsat`` is asserted for it.
#
# The receiver is a name only a star import the lifter cannot read may bind:
# a free operand nothing decides, the receiver this rule is about.  A name the
# module binds nowhere is no free operand: its read halts with ``NameError``
# (``NameSugar``, #7854) before the call, so no assertion is reached.
# ---------------------------------------------------------------------------

_UNKNOWN_RECEIVER = """\
from unread_module import *


def test_lookup():
    registry = undefined_registry
    value = registry.lookup(3)
    assert 3 == {claim}
"""


def test_a_claim_after_an_unknown_receiver_method_call_stands_on_its_completing_face(
    tmp_path: Path,
) -> None:
    true_claim = run_source_through_real_solver(
        tmp_path / "true-claim", _UNKNOWN_RECEIVER.format(claim=3)
    )
    false_claim = run_source_through_real_solver(
        tmp_path / "false-claim", _UNKNOWN_RECEIVER.format(claim=4)
    )
    print(
        json.dumps(
            {"true-claim": true_claim.verdict, "false-claim": false_claim.verdict},
            sort_keys=True,
        )
    )
    assert true_claim.verdict == "open"
    assert false_claim.verdict == "unsat"


_HELD_RECEIVER = """\
class Registry:
    def lookup(self, key):
        return key


def test_lookup():
    registry = Registry()
    value = registry.lookup(3)
    assert 3 == 3
"""


def test_unknown_receiver_method_call_is_two_faced_in_process() -> None:
    """Reduction level: the completion is guarded and the raise is a face.

    A receiver the lifter does not hold is the plain unknown call, completing
    only under ``python:unknown_callee_call.completes`` and raising otherwise.
    A receiver made by a same-file class call (``Registry()``) no longer
    completes alone: the class call is its coordinate and edge and the method
    of its result is not dispatched at the reduction (#7757 step 6, #8738), so
    it gives the same undecided faces.  Before step 6 the method body was
    applied and the call completed alone.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    _undecided_faces(_test_function_outcome(_HELD_RECEIVER))
    outcome = _test_function_outcome(_UNKNOWN_RECEIVER.format(claim=3))
    assert isinstance(outcome, ExitSet), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed and halted
    assert all(
        "python:unknown_callee_call.completes" in repr(face.guard)
        for face in completed
    )
    assert any(
        isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == "UnknownCallee:lookup"
        for face in halted
    )
