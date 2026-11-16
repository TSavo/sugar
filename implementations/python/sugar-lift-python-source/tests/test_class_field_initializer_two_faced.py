"""A class field whose initializer may raise makes the class statement two-faced.

``pandas.util.version.Version`` binds ``_regex = re.compile(..., re.VERBOSE
| re.IGNORECASE)``.  ``re.compile`` is an unknown-callee call and the flag
``|`` an undecided binary operation, so under the #7585 two-faced law the
initializer completes with one value under its completion atoms and halts
with an ``UndeterminedRaiseEffect`` otherwise.  ``ClassDefinitionSugar``
demanded one complete field value and refused.  Executing the class body now
halts with each initializer halt, sequenced in source order, and the class
exists on the one completed face.

The class statement runs where it stands: here, in ``f``'s own body.  (It
was once reached through a same-file manager's ``__init__`` building an
instance, a body no caller follows at lift any more, #7757 steps 6 and 9.)
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue

from test_builtin_container_mutation import _returns


def _faces(tmp_path, field: str):
    source = (
        "import re\n"
        "def f():\n"
        "    class V:\n"
        f"        r = {field}\n"
        "        def __init__(self):\n"
        "            pass\n"
        "    return 7\n"
    )
    return _returns(tmp_path, source)


def test_two_faced_field_initializer_halts_or_constructs(tmp_path):
    returns, halts = _faces(tmp_path, 're.compile("a", re.VERBOSE | re.IGNORECASE)')
    assert returns == [TermValue(7)]
    assert halts
    assert all(isinstance(halt, UndeterminedRaiseEffect) for halt in halts)


def test_total_field_initializer_adds_no_halt(tmp_path):
    # The lying twin: a decided initializer cannot raise.
    returns, halts = _faces(tmp_path, "1 + 2")
    assert returns == [TermValue(7)]
    assert halts == []
