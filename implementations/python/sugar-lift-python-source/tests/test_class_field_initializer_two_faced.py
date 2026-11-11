"""A class field whose initializer may raise makes the class statement two-faced.

``pandas.util.version.Version`` binds ``_regex = re.compile(..., re.VERBOSE
| re.IGNORECASE)``.  ``re.compile`` is an unknown-callee call and the flag
``|`` an undecided binary operation, so under the #7585 two-faced law the
initializer completes with one value under its completion atoms and halts
with an ``UndeterminedRaiseEffect`` otherwise.  ``ClassDefinitionSugar``
demanded one complete field value and refused.  Executing the class body now
halts with each initializer halt, sequenced in source order, and the class
exists on the one completed face.  Several distinct completed values still
refuse.
"""

from __future__ import annotations

from test_contextmanager_generator_protocol import _function_rows, _imported


def _rows(tmp_path, field: str):
    impl = (
        "import re\n"
        "class V:\n"
        f"    r = {field}\n"
        "    def __init__(self):\n"
        "        pass\n"
        "class cm:\n"
        "    def __init__(self):\n"
        "        self.v = V()\n"
        "    def __enter__(self):\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
    )
    return _function_rows(
        *_imported(tmp_path, impl, "pass", contextlib_enrolled=False)
    )[1]


def test_two_faced_field_initializer_halts_or_constructs(tmp_path):
    rows = _rows(tmp_path, 're.compile("a", re.VERBOSE | re.IGNORECASE)')
    assert ("return", 7) in rows
    assert ("halt", None) in rows
    assert set(rows) == {("halt", None), ("return", 7)}


def test_total_field_initializer_adds_no_halt(tmp_path):
    # The lying twin: a decided initializer cannot raise.
    assert _rows(tmp_path, "1 + 2") == [("return", 7)]
