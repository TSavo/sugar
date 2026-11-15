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
