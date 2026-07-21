"""f-strings: JoinedStr concatenates its parts; FormattedValue is format(value).

Modifiers -- a conversion (!r/!s/!a) or a format spec ({x:>10}) -- stay loud.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _post_term(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def test_fstring_concatenates_literal_and_interpolation():
    # f"n={z}" -> "n=" ++ format(z)
    term = _post_term('def A(z):\n    return f"n={z}"\n')
    assert term.name == "+"
    assert term.args[0].value == "n="
    assert term.args[1].name == "call:__format__"


def test_fstring_with_only_a_literal_is_the_string():
    term = _post_term('def A():\n    return f"hello"\n')
    assert type(term).__name__ == "_ConstStr" and term.value == "hello"


def test_conversion_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn('def A(z):\n    return f"{z!r}"\n').sugar()


def test_format_spec_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn('def A(z):\n    return f"{z:>3}"\n').sugar()


if __name__ == "__main__":
    test_fstring_concatenates_literal_and_interpolation()
    test_fstring_with_only_a_literal_is_the_string()
    test_conversion_stays_loud()
    test_format_spec_stays_loud()
    print("ok: f-strings concatenate; modifiers loud")
