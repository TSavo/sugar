"""A resolved frame reads its module's admitted value pins as their values.

``pandas.util.version.Version`` writes ``_regex = re.compile(r"^\\s*" +
VERSION_PATTERN + ...)`` where ``VERSION_PATTERN = _VERSION_PATTERN`` and
``_VERSION_PATTERN = r\"\"\"...\"\"\"``.  A manager or constructor frame
resolved into that module read ``VERSION_PATTERN`` as a free symbolic name:
only mutable module globals were carried into the frame, and class
constructor frames carried none.  A name the value-pin law admits (bound once
to an immutable value, never rebound), or a name bound once to such a pin,
is that value in every frame of its module.  A rebound name stays free.
"""

from __future__ import annotations

from test_contextmanager_generator_protocol import _function_rows, _imported

_TAIL = (
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
)


def _rows(tmp_path, head: str):
    return _function_rows(
        *_imported(tmp_path, head + _TAIL, "pass", contextlib_enrolled=False)
    )[1]


def test_initializer_reads_module_pin(tmp_path):
    head = (
        'P = "a"\n'
        "class cm:\n"
        "    def __init__(self):\n"
        '        self.x = "^" + P\n'
    )
    assert _rows(tmp_path, head) == [("return", 7)]


def test_class_field_of_a_constructed_class_reads_aliased_pin(tmp_path):
    head = (
        '_P = "a"\n'
        "P = _P\n"
        "class V:\n"
        '    r = "^" + P\n'
        "    def __init__(self):\n"
        "        pass\n"
        "class cm:\n"
        "    def __init__(self):\n"
        "        self.v = V()\n"
    )
    assert _rows(tmp_path, head) == [("return", 7)]


def test_rebound_module_name_stays_free(tmp_path):
    # The lying twin: a rebound name is not a pin, so the field stays loud.
    import pytest
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    head = 'P = "a"\nP = "b"\nclass cm:\n    r = "^" + P\n'
    with pytest.raises(ContextManagerResolutionConstructionGap):
        _rows(tmp_path, head)
