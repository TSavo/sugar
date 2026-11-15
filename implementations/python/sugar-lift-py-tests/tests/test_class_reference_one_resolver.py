"""A read of a module class from a function denotes that class, whatever form
the read takes after the rewrite (#7757 item 21).

#8520 made every read of a module class's name its statement's evaluation
key, so after substitution a class name in a function body is a
``DecoratedDefinitionRef``, not a ``Name``.  Every reader that decides which
definition a reference denotes asks the one resolver
(``SourceUnit.module_definition_denoted_by``), never the reference's syntax
node: a call of the class (#8535), a raised and a handled class, a base.
Which object a call of the class makes is the evaluation that made it
(``Assign._object_place_state``), never the call's fragment.

Each twin is a truthful/lying pair through the real solver: the truthful
claim is ``sat`` on the test function's own claims, the lying one ``unsat``,
once the class of a class call's result is decided at prove (#7757 step 8).
Until then both halves read ``open`` (``_assert_open_pair``).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _test_line(module: str) -> int:
    (line,) = (
        number
        for number, text in enumerate(module.splitlines(), start=1)
        if text.startswith("def test_")
    )
    return line


# Each twin below calls a same-file class inside ``f`` (``Box(3)``,
# ``Marker()``, ``Boom()``).  Since #7757 step 6 (#8738) that call is its
# coordinate and edge, and what ``f`` then needs is the class of the call's
# result: the method a ``with`` calls on it (``__enter__``, #8744), the
# class ``isinstance`` tests, the class an ``except`` tests against the
# raised instance.  Neither the reduction nor the class's contract decides
# that today (the contract states fields, never the instance's class), so
# ``f``'s row reads an undecided value and both halves read ``open`` on main
# (scorecard 43738710481; the truthful halves measured, the lies set by
# reasoning), listed on #7661.  The resolver itself (each read of the class
# name denotes the one class statement) is what the halves will witness
# once the class of the call's result is stated.
#
# Step 8 as merged (#8750 prove, #8778 and #8799 lift) does not state it
# here.  It supplies a receiver class (``python:instance(<class>,
# <field>...)``) only for the result of a class whose construction runs no
# source code (``_bare_instance_symbol``), and only to a method call on it:
# - ``Box`` and ``Marker`` run a source ``__init__``, so their call's result
#   names no class (the field set is the class contract's, which dispatch
#   does not read).  ``Box.__exit__(self, *exc)`` would not fit prove's one
#   binder either (no ``*args``), and ``box.value`` reads a field of
#   ``__enter__``'s result, which no contract states.
# - ``isinstance`` and an ``except`` test read the class of a value, not a
#   method: a type test reads no object off a call
#   (``class_definition_value._instance_held_by``), and ``with_raised_types``
#   types only a call's own raise (``python:raised(<call>, ...)``), never a
#   raised value made by a class call (``raise Boom()``).
# None of these is step 7 part 1 (what a callee leaves in what it was
# handed): each needs the class of a class call's result stated at prove.
_OPEN_UNTIL_STEP_8 = (
    "the class of a same-file class call's result is not stated at prove "
    "(#7757 step 8 supplies it only to a method call on a class whose "
    "construction runs no source code)"
)


def _assert_open_pair(tmp_path: Path, module: str, truthful: str, lying: str) -> None:
    told = run_source_through_real_solver(
        tmp_path / "t", module.format(claim=truthful)
    )
    lied = run_source_through_real_solver(tmp_path / "l", module.format(claim=lying))
    assert (
        claim_verdict(told.prove_doc, claims_from_line=_test_line(module)) == "open"
    ), _OPEN_UNTIL_STEP_8
    # Never ``sat`` for the lie.
    assert lied.verdict == "open", _OPEN_UNTIL_STEP_8


_WITH_SAME_MODULE_MANAGER = (
    "class Box:\n"
    "    def __init__(self, value):\n"
    "        self.value = value\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "\n"
    "\n"
    "def f():\n"
    "    with Box(3) as box:\n"
    "        return box.value\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_a_with_over_a_same_module_manager_class_reads_the_class(
    tmp_path: Path,
) -> None:
    """``with Box(3) as box`` in ``f``: the manager is an instance of ``Box``
    (the callee's read denotes the class statement), ``__enter__`` returns it,
    and ``box.value`` is 3."""
    _assert_open_pair(tmp_path, _WITH_SAME_MODULE_MANAGER, "3", "4")


_ISINSTANCE_SAME_MODULE_CLASS = (
    "class Marker:\n"
    "    def __init__(self):\n"
    "        self.seen = 1\n"
    "\n"
    "\n"
    "def f():\n"
    "    return isinstance(Marker(), Marker)\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_isinstance_of_a_same_module_class_reads_the_class(tmp_path: Path) -> None:
    """``isinstance(Marker(), Marker)`` in ``f``: both reads of ``Marker``
    denote the one class statement, so the instance is the class's and the
    test is True."""
    _assert_open_pair(tmp_path, _ISINSTANCE_SAME_MODULE_CLASS, "True", "False")


_RAISE_AND_HANDLE_SAME_MODULE_CLASS = (
    "class Boom(Exception):\n"
    "    pass\n"
    "\n"
    "\n"
    "def f():\n"
    "    try:\n"
    "        raise Boom()\n"
    "    except Boom:\n"
    "        return 1\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_a_same_module_exception_class_raised_and_handled_in_a_function(
    tmp_path: Path,
) -> None:
    """``raise Boom()`` and ``except Boom`` in ``f``: both reads denote the
    one class statement (its ``source-class`` identity), so the handler
    surely matches and ``f()`` is 1."""
    _assert_open_pair(tmp_path, _RAISE_AND_HANDLE_SAME_MODULE_CLASS, "1", "2")
