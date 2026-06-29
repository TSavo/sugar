"""Control flow is lifted into first-order logic, not executed. Each return path
becomes `guard -> out == expr`; the body universe is the conjunction of those
implications. z3 does the branching given the bound inputs."""
from __future__ import annotations

import json

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

CLASSIFY = (
    "def classify(value):\n"
    '    if value == "a":\n'
    '        return "alpha"\n'
    '    return "other"\n'
    "def t():\n"
    '    assert classify("a") == "{expected}"\n'
)


def test_branching_body_lifts_to_a_conjunction_of_guarded_implications():
    rep = build_literal_call_report(
        source=CLASSIFY.format(expected="alpha"), filename="c.py", memento_file="c.py"
    )
    universe = [c for c in rep.payload.ir if getattr(c, "post", None) is not None]
    assert universe, "the dig must mint a universe for the branching body"
    post = json.dumps(universe[0].post)
    # control flow == conjunction of `guard -> out == ...` implications, no execution
    assert '"kind": "and"' in post
    assert '"kind": "implies"' in post
    assert '"name": "out"' in post
