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
# raised instance.  Before step 8 stated the class (below), ``f``'s row read
# an undecided value and both halves read ``open`` on main (scorecard
# 43738710481; the truthful halves measured, the lies set by reasoning),
# listed on #7661.  The resolver itself (each read of the class name
# denotes the one class statement) is what the halves will witness once
# each claim's remaining reason is stated.
#
# Step 8 now states the class of a class call's result wherever
# ``type.__call__`` makes it with a builtin ``__new__``: the class's
# contract states ``python:type_is`` and ``python:may_hold`` on every
# completed face, a method call and a ``with``'s ``__enter__``/``__exit__``
# on the result are dispatched over it (``python:constructed``), and
# ``__exit__(self, *exc)`` fits the one binder (#8838).  The type test is
# decided at prove (``isinstance(Marker(), Marker)``: the term
# ``python:isinstance`` related to ``python:type_is`` by the isinstance law,
# #7757).  The other twins are still ``open``, by a named reason that is not
# the class of the result:
# - ``with Box(3) as box``: ``box`` is ``__enter__``'s result, and
#   ``box.value`` reads a field of it, which no contract states
#   (``__enter__`` returns ``self``, a receiver that arrived by binding).
#   Equating the returned object's fields with the manager's constructed
#   fields at prove (``out = self`` and ``python:leaves("self")``) is not
#   sound on its own: the lift does not know ``box`` and the manager are one
#   object, so a store through another name of the manager (``b = Box(3);
#   with b as box: b.value = 9``) rebinds that name and never ``box``, and
#   the read would be the constructed 3.  It stays owed until the lift
#   names ``as box`` as the manager's own object where nothing else holds
#   the manager (#7757, carried on #7661).
# ``raise Boom()`` / ``except Boom`` is decided both ways (below): the class
# contract states the ``*args``/``**kwargs`` its call packs, so ``Boom()``
# joins its constructor (#9155) and the handler's match is decided.
_OPEN_UNTIL_STEP_8 = (
    "the claim reads something step 8 does not state: a field of "
    "__enter__'s result"
)


def _assert_open_pair(
    tmp_path: Path, module: str, truthful: str, lying: str, *, lie: str = "open"
) -> None:
    """The truthful half reads `open` on the test function's claims; the lie
    reads `lie`: `open`, or `unsat` where the claim is refuted on every arm
    without the class (never `sat`)."""
    told = run_source_through_real_solver(
        tmp_path / "t", module.format(claim=truthful)
    )
    lied = run_source_through_real_solver(tmp_path / "l", module.format(claim=lying))
    assert (
        claim_verdict(told.prove_doc, claims_from_line=_test_line(module)) == "open"
    ), _OPEN_UNTIL_STEP_8
    # Never ``sat`` for the lie.
    assert lied.verdict == lie, _OPEN_UNTIL_STEP_8


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
    test is True.

    The test is the term ``python:isinstance(python:after(<Marker()>,
    "out"), "<Marker>")`` (#7757); ``Marker``'s constructor contract states
    ``python:type_is`` of the instance it makes, and prove's isinstance law
    (``Marker`` in ``Marker``'s own order, read off its namespace row) makes
    the term ``true``: truthful ``sat``, lying ``unsat``."""
    told = run_source_through_real_solver(
        tmp_path / "t", _ISINSTANCE_SAME_MODULE_CLASS.format(claim="True")
    )
    lied = run_source_through_real_solver(
        tmp_path / "l", _ISINSTANCE_SAME_MODULE_CLASS.format(claim="False")
    )
    line = _test_line(_ISINSTANCE_SAME_MODULE_CLASS)
    assert claim_verdict(told.prove_doc, claims_from_line=line) == "sat"
    assert lied.verdict == "unsat"


_ISINSTANCE_OF_ANOTHER_CLASS = (
    "class Other:\n"
    "    def __init__(self):\n"
    "        self.seen = 1\n"
    "\n"
    "\n"
    "class Plain:\n"
    "    def __init__(self):\n"
    "        self.seen = 2\n"
    "{masked}"
    "\n"
    "\n"
    "def f():\n"
    "    return isinstance(Plain(), Other)\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)

# ``Plain``'s order binds a ``__class__`` property that raises: CPython's
# ``object_isinstance`` reads ``x.__class__`` once ``type(x)`` is no subclass
# of ``Other``, so ``f`` raises ``ValueError``.
_MASKED_CLASS = (
    "    @property\n"
    "    def __class__(self):\n"
    "        raise ValueError('masked')\n"
)


def test_isinstance_of_an_unrelated_class_is_false_where_the_class_read_runs_no_code(
    tmp_path: Path,
) -> None:
    """``isinstance(Plain(), Other)``: ``type(x)`` is ``Plain``, no subclass
    of ``Other``, so ``type.__instancecheck__`` reads ``x.__class__``.  No
    class of ``Plain``'s order binds ``__class__`` or ``__getattribute__``
    and it ends in ``object`` alone, so the read is ``object.__class__``'s
    getter: it returns ``Plain`` and never raises, and the test completes
    ``False``.  Prove's isinstance law states both from ``Plain``'s
    namespace row and the ``python:type_is`` its constructor contract states
    (#7757 step 9): truthful ``sat``, lying ``unsat``."""
    module = _ISINSTANCE_OF_ANOTHER_CLASS.replace("{masked}", "")
    told = run_source_through_real_solver(tmp_path / "t", module.format(claim="False"))
    lied = run_source_through_real_solver(tmp_path / "l", module.format(claim="True"))
    line = _test_line(module)
    assert claim_verdict(told.prove_doc, claims_from_line=line) == "sat"
    assert lied.verdict == "unsat"


def test_isinstance_whose_class_read_may_run_code_keeps_its_halt_owed(
    tmp_path: Path,
) -> None:
    """``isinstance(Plain(), Other)`` with a ``__class__`` property on
    ``Plain`` that raises: the test's completion is not decided (the read
    runs the property), so its halt face stays owed and neither its value
    nor its completion is stated.  Python raises here, so every claim on
    ``f()``'s value is a lie: neither half may read ``sat``; both stay
    ``open`` (#7757 step 9: nothing states what the property does)."""
    module = _ISINSTANCE_OF_ANOTHER_CLASS.replace("{masked}", _MASKED_CLASS)
    line = _test_line(module)
    for role, claim in (("f", "False"), ("t", "True")):
        result = run_source_through_real_solver(
            tmp_path / role, module.format(claim=claim)
        )
        assert claim_verdict(result.prove_doc, claims_from_line=line) == "open", claim


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
    surely matches and ``f()`` is 1.

    The lie (`f() == 2`) is refuted without the class: `f`'s one
    completing arm is the handler's `return 1`, and the arm where the
    handler does not take the raise halts, so wherever `f()` completes it is
    1 (scorecard 43745139407 measured `unsat`).  The truthful half is `sat`
    since ``Boom``'s contract states the ``*args``/``**kwargs`` its call
    packs and ``raise Boom()`` joins its constructor (#9155): the class of
    the raised value is stated, the handler surely takes it, and `f()`
    completes 1 (scorecard 44005532618 on 13e3413ad: truthful `green`,
    lying `refuted`)."""
    told = run_source_through_real_solver(
        tmp_path / "t", _RAISE_AND_HANDLE_SAME_MODULE_CLASS.format(claim="1")
    )
    lied = run_source_through_real_solver(
        tmp_path / "l", _RAISE_AND_HANDLE_SAME_MODULE_CLASS.format(claim="2")
    )
    line = _test_line(_RAISE_AND_HANDLE_SAME_MODULE_CLASS)
    assert claim_verdict(told.prove_doc, claims_from_line=line) == "sat"
    assert lied.verdict == "unsat"
