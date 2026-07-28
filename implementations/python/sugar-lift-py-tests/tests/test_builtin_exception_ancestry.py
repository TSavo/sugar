"""Builtin exception ancestry is VENDOR testimony, not an empty assumption.

Python owns its exception hierarchy. `ValueError` IS an `Exception`; the
language says so, in the interpreter that also compiles the corpus. Until
this file existed the kit carried `bases=()` for every builtin exception
class and a singleton `(identity,)` for every builtin ancestry, so:

    try:
        raise ValueError("boom")
    except Exception:
        ...

did not catch — the matcher walked an ancestry that had been fabricated as
empty and answered "no match" by SILENCE about a fact the vendor states.

That is the forbidden shape: a decided `False` standing in for an ancestry
nobody authenticated. Both faces are pinned here — the ones that must match
AND the ones that must not — because an ancestry table that says yes to
everything is exactly as wrong as one that says no to everything.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.outcome import Incomplete, outcome_to_exitset
from sugar_source_tree.tree import SourceFile


def _residual_raises(source: str) -> tuple[str, ...]:
    """Every raise that survived the `try` — the effects still on the wall."""
    from sugar_lift_python_source.canonical import blake3_512_of

    source_file = SourceFile((source, "/tmp/ancestry.py", blake3_512_of(source.encode())))
    function = next(iter(source_file.functions()))
    exit_set = outcome_to_exitset(function.sugar().desugar())
    names: list[str] = []
    seen: set[int] = set()

    def walk(value: object) -> None:
        if value is None or isinstance(value, (str, int, bool, float, bytes)):
            return
        key = id(value)
        if key in seen:
            return
        seen.add(key)
        if isinstance(value, Incomplete) and isinstance(value.effect, RaiseEffect):
            names.append(value.effect.exception_name)
        effect = getattr(value, "effect", None)
        if isinstance(effect, RaiseEffect):
            names.append(effect.exception_name)
        for attribute in ("statements", "record", "value", "exits"):
            child = getattr(value, attribute, None)
            if isinstance(child, tuple):
                for item in child:
                    walk(item)
            else:
                walk(child)

    for face in exit_set.exits:
        walk(face)
    return tuple(sorted(set(names)))


def _try_source(*, raised: str, handled: str) -> str:
    return (
        "def f():\n"
        "    try:\n"
        f"        raise {raised}('boom')\n"
        f"    except {handled}:\n"
        "        return 1\n"
        "    return 2\n"
    )


# --- faces that MUST match (ancestry is real) --------------------------------


def test_except_exception_catches_value_error():
    assert _residual_raises(_try_source(raised="ValueError", handled="Exception")) == ()


def test_except_arithmetic_error_catches_zero_division_error():
    assert (
        _residual_raises(
            _try_source(raised="ZeroDivisionError", handled="ArithmeticError")
        )
        == ()
    )


def test_except_os_error_catches_file_not_found_error():
    assert (
        _residual_raises(_try_source(raised="FileNotFoundError", handled="OSError"))
        == ()
    )


def test_except_base_exception_catches_keyboard_interrupt():
    assert (
        _residual_raises(
            _try_source(raised="KeyboardInterrupt", handled="BaseException")
        )
        == ()
    )


# --- faces that MUST NOT match (the ancestry table has to say no, too) -------


def test_except_value_error_does_not_catch_type_error():
    assert _residual_raises(_try_source(raised="TypeError", handled="ValueError")) == (
        "TypeError",
    )


def test_ancestry_is_directional_subclass_does_not_catch_superclass():
    """`except ValueError` must NOT catch a bare `Exception`.

    The perturbation that a permissive table would pass: ancestry is a
    partial order, not a symmetric relation.
    """
    assert _residual_raises(_try_source(raised="Exception", handled="ValueError")) == (
        "Exception",
    )


def test_except_arithmetic_error_does_not_catch_os_error():
    assert _residual_raises(_try_source(raised="OSError", handled="ArithmeticError")) == (
        "OSError",
    )


def test_keyboard_interrupt_is_not_an_exception():
    """`except Exception` must NOT catch `KeyboardInterrupt`.

    The one place the real hierarchy differs from the naive "everything is an
    Exception" table, and the reason the table is transported rather than
    assumed.
    """
    assert _residual_raises(
        _try_source(raised="KeyboardInterrupt", handled="Exception")
    ) == ("KeyboardInterrupt",)
