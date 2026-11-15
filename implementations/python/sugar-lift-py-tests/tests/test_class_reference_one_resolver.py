"""A read of a module class from a function denotes that class, whatever form
the read takes after the rewrite (#7757 item 21).

#8520 made every read of a module class's name its statement's evaluation
key, so after substitution a class name in a function body is a
``DecoratedDefinitionRef``, not a ``Name``.  Every reader that decides which
definition a reference denotes asks the one resolver
(``SourceUnit.module_definition_denoted_by``), never the reference's syntax
node: a call of the class (#8535), a raised and a handled class, a base.

Each twin is a truthful/lying pair through the real solver: the truthful
claim is ``sat`` on the test function's own claims, the lying one ``unsat``.
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


def _assert_pair(tmp_path: Path, module: str, truthful: str, lying: str) -> None:
    told = run_source_through_real_solver(
        tmp_path / "t", module.format(claim=truthful)
    )
    lied = run_source_through_real_solver(tmp_path / "l", module.format(claim=lying))
    assert claim_verdict(told.prove_doc, claims_from_line=_test_line(module)) == "sat"
    assert lied.verdict == "unsat"


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
    _assert_pair(tmp_path, _WITH_SAME_MODULE_MANAGER, "3", "4")


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
    _assert_pair(tmp_path, _ISINSTANCE_SAME_MODULE_CLASS, "True", "False")


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
    _assert_pair(tmp_path, _RAISE_AND_HANDLE_SAME_MODULE_CLASS, "1", "2")
