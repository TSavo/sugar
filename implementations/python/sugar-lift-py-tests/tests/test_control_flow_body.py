"""Control flow is lifted into first-order logic, not executed. Each return path
becomes `guard -> out == expr`; the body universe is the conjunction of those
implications. z3 does the branching given the bound inputs."""

from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

CLASSIFY = (
    "def classify(value):\n"
    '    if value == "a":\n'
    '        return "alpha"\n'
    '    return "other"\n'
    "def t():\n"
    '    assert classify("a") == "{expected}"\n'
)

# A branch returns the PARAM itself -- the value must flow through symbolically.
PASSTHROUGH = (
    "def pick(s):\n"
    '    if s == "x":\n'
    "        return s\n"
    '    return "default"\n'
    "def t():\n"
    '    assert pick("x") == "x"\n'
)

# A branch returns an OPERATION over the param. The symbolic-operation sugars are
# not written yet, so the factory must PANIC (name the gap), never mislift.
ARITHMETIC = (
    "def step(n):\n"
    "    if n == 0:\n"
    "        return 100\n"
    "    return n + 1\n"
    "def t():\n"
    "    assert step(0) == 100\n"
)


def _universe_post(source: str):
    rep = build_literal_call_report(source=source, filename="c.py", memento_file="c.py")
    universe = [c for c in rep.payload.ir if getattr(c, "post", None) is not None]
    assert universe, "the dig must mint a universe for the branching body"
    return json.dumps(universe[0].post)


def test_branching_body_lifts_to_a_conjunction_of_guarded_implications():
    post = _universe_post(CLASSIFY.format(expected="alpha"))
    # control flow == conjunction of `guard -> out == ...` implications, no execution
    assert '"kind": "and"' in post
    assert '"kind": "implies"' in post
    assert '"name": "out"' in post


def test_param_passthrough_return_flows_through_symbolically():
    # the `return s` branch lifts to `out == s` -- the param is a sort-neutral
    # symbolic var, not a computed value, so it carries straight into the universe.
    post = _universe_post(PASSTHROUGH)
    assert '"kind": "implies"' in post
    # both `out` and the param `s` appear as bare vars in an equality
    assert '"name": "out"' in post
    assert '{"kind": "var", "name": "s"}' in post


def test_symbolic_operation_return_emits_the_op_into_the_universe():
    # `return n + 1` is no longer a panic: the cf-walker EMITS the operation `+(n, 1)` into the
    # universe post (sort-silent), so the body's source line is warranted. The SMT compiler
    # derives n's carrier from the `+` it appears in. Emitting the operation IS the lift.
    post = _universe_post(ARITHMETIC)
    assert '"name": "+"' in post
    assert '{"kind": "var", "name": "n"}' in post
