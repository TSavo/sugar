"""A binding that depends on which route left a ``try`` is joined over that route.

``flag = 0; try: textwrap.dedent("x") except ValueError: flag = 1`` leaves
``flag`` as ``1`` when the handler ran and ``0`` when the body completed.  The
source tree dropped the name whenever the routes disagreed, so the read after
the try saw the pre-try ``0`` and ``if flag: raise KeyError`` never raised.

The join is now the one ``if`` already uses: an if-expression over the try's
``try-route:<site>:<k>`` slot, handler arms in source order and the body route
innermost.  ``TrySugar`` confirms the slots on every routed outcome -- handler
``k`` ran: slot ``k`` true and the others false; the body completed: every
slot false -- and grounds them when every completed outcome took one route.

These tests read the lifted faces propositionally: every atom is an opaque
boolean, the theory is the facts each face states under that face's own guard,
and a claim holds under a route when the theory and that route's guard entail
it.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
)
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.ir import _Atomic, _Connective, and_, implies, not_
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

from test_undetermined_raise_except_matching import _exits


def _atoms(formula, out):
    if isinstance(formula, _Atomic):
        out.setdefault(formula, None)
    elif isinstance(formula, _Connective):
        for operand in formula.operands:
            _atoms(operand, out)
    return out


def _holds(formula, env):
    if isinstance(formula, _Atomic):
        return env[formula]
    values = [_holds(operand, env) for operand in formula.operands]
    if formula.kind == "and":
        return all(values)
    if formula.kind == "or":
        return any(values)
    if formula.kind == "not":
        return not values[0]
    if formula.kind == "implies":
        return (not values[0]) or values[1]
    raise AssertionError(formula.kind)


class _Lift:
    """The function's faces, its stated theory, and a propositional reader."""

    def __init__(self, exits):
        self.exits = exits
        self.theory = []
        self.returns = []  # (face guard, returned value)
        self.halts = []  # (guard, effect)
        for face in exits.exits:
            # A face's facts hold where the face does: each is read under
            # the face's own guard, never as a global axiom.
            if isinstance(face, Halted):
                self.halts.append((face.guard, face.effect))
                state = face.state
                entries = getattr(state, "entries", None)
                if entries is None:
                    entries = getattr(getattr(state, "record", None), "statements", ())
                self._facts(face.guard, entries)
                continue
            record = getattr(face.value, "record", None)
            statements = getattr(record, "statements", ())
            self._facts(face.guard, statements)
            for entry in statements:
                name = type(entry).__name__
                if name == "ReturnValue":
                    self.returns.append((face.guard, entry.value))
                elif name == "GuardedReturn":
                    self.returns.append(
                        (and_([face.guard, *entry.guards]), entry.value)
                    )
                elif isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                    for halt in entry.halts():
                        self.halts.append(
                            (and_([face.guard, halt.guard]), halt.effect)
                        )

    def _facts(self, guard, entries):
        for entry in entries:
            if isinstance(entry, BranchResultAuthentication):
                facts = entry.inv_contribution()
            elif type(entry).__name__ == "InvValue":
                facts = (entry.formula,)
            else:
                continue
            self.theory.extend(implies(guard, fact) for fact in facts)

    def atom(self, name, *needles):
        found = {}
        for formula in [*self.theory, *(g for g, _ in self.halts), *(g for g, _ in self.returns)]:
            _atoms(formula, found)
        matches = [
            atom
            for atom in found
            if atom.name == name and all(n in repr(atom) for n in needles)
        ]
        assert len(matches) == 1, (name, needles, matches)
        return matches[0]

    def models(self, assumption):
        found = {}
        formulas = [*self.theory, assumption]
        formulas += [g for g, _ in self.halts] + [g for g, _ in self.returns]
        for formula in formulas:
            _atoms(formula, found)
        for value in (v for _, v in self.returns):
            for guard in _value_guards(value):
                _atoms(guard, found)
        keys = list(found)
        assert len(keys) <= 16, len(keys)
        for bits in itertools.product((False, True), repeat=len(keys)):
            env = dict(zip(keys, bits))
            if _holds(assumption, env) and all(_holds(t, env) for t in self.theory):
                yield env

    def outcomes_under(self, assumption):
        """Every (kind, payload) the function can leave by under ``assumption``."""
        seen = set()
        any_model = False
        for env in self.models(assumption):
            any_model = True
            for guard, value in self.returns:
                if _holds(guard, env):
                    seen.add(("return", _value_under(value, env)))
            for guard, effect in self.halts:
                if _holds(guard, env):
                    seen.add(("halt", _effect_name(effect)))
        assert any_model, "route assumption is unsatisfiable under the theory"
        return seen


def _value_guards(value):
    if isinstance(value, GuardedValue):
        yield value.guard
        yield from _value_guards(value.when_true)
        yield from _value_guards(value.when_false)


def _value_under(value, env):
    while isinstance(value, GuardedValue):
        value = value.when_true if _holds(value.guard, env) else value.when_false
    return getattr(value, "value", repr(value))


def _effect_name(effect):
    name = getattr(effect, "exception_name", None)
    return name if name is not None else type(effect).__name__


def _lift(tmp_path: Path, source: str) -> _Lift:
    return _Lift(_exits(tmp_path, source))


def _routes(lift, *handler_types):
    """The completed route and one route per handler, as guards."""
    completes = lift.atom("python:source_call.completes", "dedent")
    caught = [
        lift.atom("adt.is_python_type", "dedent", f"'{name}'") for name in handler_types
    ]
    routes = {"body": completes}
    for index, name in enumerate(handler_types):
        routes[name] = and_(
            [not_(completes), *(not_(c) for c in caught[:index]), caught[index]]
        )
    return routes


REPRODUCER = '''import textwrap
def f():
    flag = 0
    try:
        textwrap.dedent("x")
    except ValueError:
        flag = 1
    if flag:
        raise KeyError("k")
    return 2
'''


def test_handler_route_flag_raises_and_completed_route_returns(tmp_path):
    lift = _lift(tmp_path, REPRODUCER)
    routes = _routes(lift, "ValueError")
    assert lift.outcomes_under(routes["ValueError"]) == {("halt", "KeyError")}
    assert lift.outcomes_under(routes["body"]) == {("return", 2)}
    assert any(
        isinstance(effect, RaiseEffect) and effect.exception_name == "KeyError"
        for _guard, effect in lift.halts
    )


def test_body_and_handler_assignments_join_over_the_route(tmp_path):
    lift = _lift(
        tmp_path,
        '''import textwrap
def f():
    try:
        textwrap.dedent("a")
        x = "b"
    except ValueError:
        x = "h"
    return x
''',
    )
    routes = _routes(lift, "ValueError")
    assert lift.outcomes_under(routes["ValueError"]) == {("return", "h")}
    assert lift.outcomes_under(routes["body"]) == {("return", "b")}


def test_each_handler_route_carries_its_own_value(tmp_path):
    lift = _lift(
        tmp_path,
        '''import textwrap
def f():
    flag = 0
    try:
        textwrap.dedent("a")
    except ValueError:
        flag = 1
    except KeyError:
        flag = 2
    return flag
''',
    )
    routes = _routes(lift, "ValueError", "KeyError")
    assert lift.outcomes_under(routes["ValueError"]) == {("return", 1)}
    assert lift.outcomes_under(routes["KeyError"]) == {("return", 2)}
    assert lift.outcomes_under(routes["body"]) == {("return", 0)}


def test_else_is_the_body_route_and_finally_reads_the_join(tmp_path):
    lift = _lift(
        tmp_path,
        '''import textwrap
def f():
    flag = 0
    try:
        textwrap.dedent("a")
    except ValueError:
        flag = 1
    else:
        flag = 2
    finally:
        done = flag
    return done
''',
    )
    routes = _routes(lift, "ValueError")
    assert lift.outcomes_under(routes["ValueError"]) == {("return", 1)}
    assert lift.outcomes_under(routes["body"]) == {("return", 2)}


def test_a_name_bound_only_by_the_handler_is_unbound_on_the_body_route(tmp_path):
    lift = _lift(
        tmp_path,
        '''import textwrap
def f():
    try:
        textwrap.dedent("a")
    except ValueError:
        y = 1
    return y
''',
    )
    routes = _routes(lift, "ValueError")
    assert lift.outcomes_under(routes["ValueError"]) == {("return", 1)}
    assert lift.outcomes_under(routes["body"]) == {("halt", "UnboundLocalError")}


def test_a_ground_raise_caught_by_a_decided_except_is_one_value(tmp_path):
    lift = _lift(
        tmp_path,
        '''def f():
    flag = 0
    try:
        raise ValueError("v")
    except ValueError:
        flag = 1
    return flag
''',
    )
    assert [value.value for _guard, value in lift.returns] == [1]
    assert not lift.halts
    assert "try-route" not in repr(lift.exits)


def test_a_body_that_cannot_halt_at_reduction_grounds_the_body_route(tmp_path):
    lift = _lift(
        tmp_path,
        '''def f():
    flag = 0
    try:
        flag = 1 + 1
    except ValueError:
        flag = 5
    return flag
''',
    )
    assert [value.value for _guard, value in lift.returns] == [2]
    assert not lift.halts


def test_an_if_phi_is_guarded_by_the_if_own_slot(tmp_path):
    """The phi's if-expression reads the slot its ``if`` authenticates, not a
    second slot minted from the reference's span that nothing confirms."""
    lift = _lift(
        tmp_path,
        '''def f(p):
    flag = 0
    if p is None:
        flag = 1
    if flag:
        raise KeyError("k")
    return 2
''',
    )
    is_none = lift.atom("identity")
    assert lift.outcomes_under(is_none) == {("halt", "KeyError")}
    assert lift.outcomes_under(not_(is_none)) == {("return", 2)}
