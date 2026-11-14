"""``except tuple(types):`` reads its type when a raise reaches the arm (#7665).

pandas.io.common ``_get_filepath_or_buffer`` writes
``except tuple(err_types_to_retry_with_anon):``.  CPython evaluates a handler
expression only when an exception reaches it and matches a tuple by any
member (an empty tuple matches nothing).  A value that is not exception
classes stays loud.
"""

import pytest

from sugar_source_tree.panic import SugarNotWritten

from test_try_sugar import _fn


def _raised(src: str) -> list:
    """Exception names on the faces that leave ``A`` raising."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    names = []
    for face in _fn(src).sugar().desugar().exits:
        if isinstance(face, Halted):
            names.append(face.effect.exception_name)
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()) or ():
            if isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                names.extend(
                    getattr(halt.effect, "exception_name", None)
                    for halt in entry.halts()
                )
    return names


def _src(types: str) -> str:
    return (
        "def A(z):\n"
        f"    types = {types}\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except tuple(types):\n"
        "        pass\n"
        "    return z\n"
    )


def test_a_listed_class_catches() -> None:
    assert _raised(_src("[KeyError, ValueError]")) == []


def test_an_empty_tuple_catches_nothing() -> None:
    assert _raised(_src("[]")) == ["ValueError"]


def test_an_unlisted_class_does_not_catch() -> None:
    assert _raised(_src("[KeyError]")) == ["ValueError"]


def test_a_non_class_member_stays_loud() -> None:
    # CPython: TypeError, catching classes that do not inherit from
    # BaseException is not allowed.  Not modelled, so not claimed.
    with pytest.raises(SugarNotWritten):
        _raised(_src("[1]"))
