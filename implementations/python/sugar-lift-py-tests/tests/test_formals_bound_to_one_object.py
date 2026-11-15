"""Two formals bound to one object at a followed call (#7757).

A formal at a followed call is the caller's actual with the caller's
currency (``object_identity.contents_current``).  The body's construction
holds two formals as two objects (each its own coordinate), so a store
through one rebinds that formal alone: in ``f(xs, xs)`` the other formal
would still read the contents from before the store as current.  The alias
rule at the one bind door (``object_identity.as_bound_formals``) binds every
actual another actual of the same call may reach with its state unknown
(``arrived_as``), so no read takes contents the object may no longer hold.

A followed call's binding states its kind by its type
(``FormalActualBinding``), never by its blame text.
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.object_identity import (
    as_bound_formals,
    contents_current,
)
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_one_object_bound_to_two_formals_is_bound_with_its_state_unknown():
    xs = ListValue((TermValue(1),), allocation="xs-site")
    a, b = as_bound_formals((xs, xs), ("formal-a", "formal-b"))
    assert not contents_current(a) and a.arrival == "formal-a"
    assert not contents_current(b) and b.arrival == "formal-b"


def test_an_actual_another_actual_holds_is_bound_with_its_state_unknown():
    xs = ListValue((TermValue(1),), allocation="xs-site")
    a, b = as_bound_formals((xs, TupleValue((xs,))), ("formal-a", "formal-b"))
    assert not contents_current(a)
    assert not contents_current(b.elements[0])


def test_two_objects_keep_the_callers_currency():
    xs = ListValue((TermValue(1),), allocation="xs-site")
    ys = ListValue((), allocation="ys-site")
    a, b = as_bound_formals((xs, ys), ("formal-a", "formal-b"))
    assert a is xs and b is ys
    three = TermValue(3)
    one, two = as_bound_formals((three, three), ("formal-a", "formal-b"))
    assert one is three and two is three


def test_a_call_joined_at_prove_asks_the_alias_rule_s_own_test():
    """``definition_edge_call`` joins no contract to a call that binds one
    object to two formals: the same test as ``as_bound_formals``."""
    from sugar_lift_py_tests.floor.object_identity import actuals_share_an_object

    xs = ListValue((TermValue(1),), allocation="xs-site")
    ys = ListValue((), allocation="ys-site")
    assert actuals_share_an_object((xs, xs))
    assert actuals_share_an_object((xs, TupleValue((xs,))))
    assert not actuals_share_an_object((xs, ys))
    assert not actuals_share_an_object((TermValue(3), TermValue(3)))
    assert not actuals_share_an_object((xs,))


def test_a_formal_binding_states_its_kind_by_its_type():
    from sugar_lift_py_tests.temporal.temporal_binding import (
        FormalActualBinding,
        TemporalBinding,
    )
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    value = TermValue(3)
    temporal = TemporalContext.empty().bind_value(
        "x", value, blame="<callsite>", kind=FormalActualBinding
    )
    assert isinstance(temporal.latest("x"), FormalActualBinding)
    # Any other write of the name is a plain binding, whatever its blame.
    rebound = temporal.bind_value("x", value, blame="<callsite>")
    assert type(rebound.latest("x")) is TemporalBinding


def _never_lies(tmp_path: Path, name: str, source: str, *, true: str, false: str):
    """The true claim is never refuted and the false one is never decided."""
    t = run_source_through_real_solver(
        tmp_path / f"{name}-true", source.format(claim=true)
    )
    f = run_source_through_real_solver(
        tmp_path / f"{name}-false", source.format(claim=false)
    )
    print(json.dumps({"true": t.verdict, "false": f.verdict}, sort_keys=True))
    assert t.verdict != "unsat"
    assert f.verdict != "sat"


_LIST_THROUGH_ONE_FORMAL = """\
def grow(a, b):
    a.append(1)
    return len(b)


def test_grow():
    xs = []
    n = grow(xs, xs)
    assert n == {claim}
"""


def test_an_append_through_one_formal_is_seen_through_the_other(tmp_path: Path):
    """``grow(xs, xs)``: ``len(b)`` after ``a.append(1)`` is 1, never the 0
    the contents before the append would say."""
    _never_lies(tmp_path, "list", _LIST_THROUGH_ONE_FORMAL, true="1", false="0")


_TWO_FORMALS_RELATED_AFTER_A_STORE = """\
def diff(a, b):
    a.append(1)
    return len(a) - len(b)


def test_diff():
    xs = []
    n = diff(xs, xs)
    assert n == {claim}
"""


def test_a_post_relating_two_formals_is_never_applied_to_one_object(
    tmp_path: Path,
):
    """``diff(xs, xs)`` is 0.  The callee's contract states ``len(a) + 1 -
    len(b)`` over two objects' entry values; read with both standing as one
    opaque object it would say 1.  The call is joined to no contract
    (``actuals_share_an_object``), so the lie is never decided."""
    _never_lies(
        tmp_path, "related", _TWO_FORMALS_RELATED_AFTER_A_STORE, true="0", false="1"
    )


_FIELD_THROUGH_ONE_FORMAL = """\
class Box:
    def __init__(self):
        self.n = 0


def poke(a, b):
    a.n = 1
    return b.n


def test_poke():
    box = Box()
    value = poke(box, box)
    assert value == {claim}
"""


def test_a_field_store_through_one_formal_is_seen_through_the_other(
    tmp_path: Path,
):
    """``poke(box, box)``: ``b.n`` after ``a.n = 1`` is 1, never the 0
    ``__init__`` stored."""
    _never_lies(tmp_path, "field", _FIELD_THROUGH_ONE_FORMAL, true="1", false="0")


def test_a_global_the_callee_reads_is_asked_with_the_actuals():
    """A function's own proof reads a module global as its free input
    (``global:G``): one input is one object, so an actual that is, or holds,
    it shares an object with the global the callee reads; two inputs, or an
    input and a fresh list, do not."""
    from sugar_lift_py_tests.contract_input import ContractInputV1
    from sugar_lift_py_tests.floor.object_identity import actuals_share_an_object

    g = ContractInputV1.mint(
        owner_definition_cid="test", input_kind="global", name="G"
    ).value()
    h = ContractInputV1.mint(
        owner_definition_cid="test", input_kind="global", name="H"
    ).value()
    cell = ContractInputV1.mint(
        owner_definition_cid="test", input_kind="cell", name="G"
    ).value()
    xs = ListValue((), allocation="xs-site")
    assert actuals_share_an_object((g, g))
    assert actuals_share_an_object((TupleValue((g,)), g))
    assert actuals_share_an_object((cell, cell))
    assert not actuals_share_an_object((g, h))
    assert not actuals_share_an_object((g, cell))
    assert not actuals_share_an_object((xs, g))


_LIST_THROUGH_A_FORMAL_AND_A_GLOBAL = """\
G = []


def grow(a):
    a.append(1)
    return len(G)


def test_grow():
    n = grow(G)
    assert n == {claim}
"""


def test_an_append_through_a_formal_is_seen_through_the_global(tmp_path: Path):
    """``grow(G)`` where ``grow`` reads ``G``: ``len(G)`` after
    ``a.append(1)`` is 1, never the 0 the module bound."""
    _never_lies(
        tmp_path,
        "global",
        _LIST_THROUGH_A_FORMAL_AND_A_GLOBAL,
        true="1",
        false="0",
    )


_LIST_THROUGH_A_FORMAL_AND_A_CELL = """\
def test_grow():
    xs = []

    def grow(a):
        a.append(1)
        return len(xs)

    n = grow(xs)
    assert n == {claim}
"""


def test_an_append_through_a_formal_is_seen_through_the_cell(tmp_path: Path):
    """``grow(xs)`` where ``grow`` reads the captured ``xs``: ``len(xs)``
    after ``a.append(1)`` is 1, never the 0 the cell held."""
    _never_lies(
        tmp_path,
        "cell",
        _LIST_THROUGH_A_FORMAL_AND_A_CELL,
        true="1",
        false="0",
    )


def test_a_dispatched_call_asks_the_alias_rule_of_its_receiver():
    """``receiver_dispatch.dispatch_edge_call`` asks the same test of its
    receiver with its actuals.  A field input ``field:p.items`` is the field
    of ``p``: it is held by ``p``, never by another field of ``p``.  A value
    that arrived names its object by its arrival."""
    from sugar_lift_py_tests.contract_input import ContractInputV1
    from sugar_lift_py_tests.floor.object_identity import (
        _reaches,
        actuals_share_an_object,
    )

    def field(name):
        return ContractInputV1.mint(
            owner_definition_cid="m", input_kind="field", name=name
        ).value()

    assert actuals_share_an_object((field("self.items"), field("self.items")))
    assert not actuals_share_an_object((field("self.items"), field("self.other")))
    assert _reaches({(("formal", "self"),)}, {(("formal", "self"), "items")})
    assert not _reaches({(("formal", "self"),)}, {(("formal", "other"), "items")})
    xs = ListValue((), allocation=None, arrival="read-xs")
    ys = ListValue((), allocation=None, arrival="read-ys")
    assert actuals_share_an_object((xs, TupleValue((xs,))))
    assert not actuals_share_an_object((xs, ys))


_RECEIVER_PASSED_TO_ITS_OWN_METHOD = """\
class Box:
    def __init__(self):
        self.items = []

    def grow(self, other):
        self.items.append(1)
        return len(other.items)


def test_grow():
    box = Box()
    n = box.grow(box)
    assert n == {claim}
"""


def test_a_store_through_the_receiver_is_seen_through_the_actual(tmp_path: Path):
    """``box.grow(box)``: ``len(other.items)`` after ``self.items.append(1)``
    is 1, never the 0 ``__init__`` stored."""
    _never_lies(
        tmp_path,
        "receiver",
        _RECEIVER_PASSED_TO_ITS_OWN_METHOD,
        true="1",
        false="0",
    )


_RECEIVER_FIELD_PASSED_TO_ITS_OWN_METHOD = """\
class Box:
    def __init__(self):
        self.items = []

    def grow(self, items):
        self.items.append(1)
        return len(items)


def via(box):
    return box.grow(box.items)


def test_grow():
    n = via(Box())
    assert n == {claim}
"""


def test_a_store_through_the_receiver_is_seen_through_its_field(tmp_path: Path):
    """``box.grow(box.items)`` on a parameter: ``len(items)`` after
    ``self.items.append(1)`` is 1, never the 0 ``__init__`` stored."""
    _never_lies(
        tmp_path,
        "receiver-field",
        _RECEIVER_FIELD_PASSED_TO_ITS_OWN_METHOD,
        true="1",
        false="0",
    )


_ITEM_STORE_ON_A_FORMAL = """\
def put(a):
{store}


def test_put():
    xs = [0]
    put(xs)
    assert xs[0] == {{claim}}
"""

_ITEM_STORE_SPELLINGS = (
    "    a[0] = 2",
    "    n, a[0] = 1, 2",
    "    for a[0] in [2]:\n        pass",
)


def test_an_item_store_on_a_formal_is_one_store_whatever_its_spelling(
    tmp_path: Path,
):
    """``a[0] = 2``, ``n, a[0] = 1, 2`` and ``for a[0] in [2]`` are one
    store on the formal's object: each makes ``a`` a ``class:`` input and
    is the dispatched ``__setitem__`` (``nodes._receiver_uses``), so the
    caller's claims get one verdict, and the lie is never ``sat``."""
    verdicts = []
    for index, store in enumerate(_ITEM_STORE_SPELLINGS):
        source = _ITEM_STORE_ON_A_FORMAL.format(store=store)
        t = run_source_through_real_solver(
            tmp_path / f"store-{index}-true", source.format(claim="2")
        )
        f = run_source_through_real_solver(
            tmp_path / f"store-{index}-false", source.format(claim="0")
        )
        print(json.dumps({"store": store, "true": t.verdict, "false": f.verdict}))
        assert t.verdict != "unsat"
        assert f.verdict != "sat"
        verdicts.append((t.verdict, f.verdict))
    assert len(set(verdicts)) == 1, verdicts
