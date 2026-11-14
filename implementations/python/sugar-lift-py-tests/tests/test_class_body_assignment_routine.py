"""Plan row 7 (steps 5 and 6), map item 1: a class field is an assignment.

A class body used to sequence its own fields.  It asked of each right-hand
side only "is it one ``Complete``" and stored the value, so ``limit = 1 // 0``
(a ``Complete`` that carries the raise as data) became the field's value and
the class statement completed (#7799).  The same question, asked with no
context, stored ``int("x")`` as a plain value: a call reduced with no context
has no raise face.

Each field's right-hand side now goes through ``evaluate_assignment_values``,
the routine every other assignment uses.  A raise of a right-hand side is the
class statement's halt, no later field runs under it, and no class exists on
that face.

An undefined name (``limit = nope``) is the same halt by the same routine: a
read of a name nothing binds is a ``NameError`` halt (#7854), so the class
statement halts with it and no class exists.

Not in this change, and pinned below as what still happens:

- a field whose right-hand side has several completed values still refuses by
  name.  Carrying those faces would build one class per value: a completion
  where there is a refusal, which is its own change.
- the solver gives no verdict on a claim whose falsity is a raise: halted arms
  of a reduction are not emitted (#7766).  The twin's lying half is "not
  ``sat``", and the ``unsat`` it should be is marked expected-red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)

_PRELUDE = (
    "import os\n"
    "\n"
    "FLAG = os.environ.get('F')\n"
    "S = os.environ.get('S')\n"
    "\n"
    "\n"
)
_INIT = "\n    def __init__(self, n):\n        self.n = n\n\n    def get(self):\n        return self.n\n\n\n"

# Class bodies in which a field always raises ``ZeroDivisionError``.
_ALWAYS_RAISES = {
    "only-field": "    limit = 1 // 0\n",
    "second-of-three": "    a = 1\n    limit = 1 // 0\n    b = 2\n",
    "chained": "    a = b = 1 // 0\n",
    "annotated": "    limit: int = 1 // 0\n",
    "nested-class": "    class Inner:\n        limit = 1 // 0\n",
    "under-if-true": "    if True:\n        limit = 1 // 0\n",
    # A later field does not run after the raise: no ``os.environ`` face.
    "before-a-may-raise": '    limit = 1 // 0\n    a = int(os.environ["L"])\n',
    # The raise sits behind a field that may itself raise.
    "after-a-may-raise": '    a = int(os.environ["L"])\n    limit = 1 // 0\n',
}


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _class_statement(body: str, *, with_context: bool):
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_source_tree import nodes

    tree = _tree(_PRELUDE + "class Box:\n" + body + _INIT)
    (box,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.ClassDef) and node.name == "Box"
    )
    ctx = ReduceContext.root(owner="test_class_body") if with_context else None
    return box.sugar().desugar(ctx)


def _function(body: str, use: str):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    tree = _tree(_PRELUDE + "class Box:\n" + body + _INIT + "def test_box():\n" + use)
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "test_box"
    )
    return function_universe_outcome(function)


def _faces(outcome) -> tuple[int, tuple[str, ...]]:
    """(completed faces, the effect of each halted face) of an outcome."""
    from sugar_lift_py_tests.outcome import (
        Complete,
        Completed,
        ExitSet,
        Halted,
        Incomplete,
    )

    if isinstance(outcome, Incomplete):
        # A halt spelled linearly (a class statement whose body raises).
        assert not outcome.follow().continues, outcome
        return 0, (repr(outcome.effect),)
    if isinstance(outcome, Complete):
        assert outcome.follow().continues, outcome
        return 1, ()
    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(repr(face.effect) for face in outcome.exits if isinstance(face, Halted)),
    )


# ---------------------------------------------------------------------------
# #7799: a class body that always raises halts the class statement.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_context", [False, True], ids=["no-ctx", "root-ctx"])
@pytest.mark.parametrize("shape", sorted(_ALWAYS_RAISES))
def test_a_class_body_that_always_raises_halts_the_class_statement(
    shape: str, with_context: bool
) -> None:
    completed, halts = _faces(
        _class_statement(_ALWAYS_RAISES[shape], with_context=with_context)
    )

    assert completed == 0
    assert sum("ZeroDivisionError" in halt for halt in halts) == 1
    if shape == "before-a-may-raise":
        # The field after the raise never ran: the statement has that one halt.
        assert len(halts) == 1


# What a function that uses the raising class reduces to.  ``halted`` is one
# halted face, the ``ZeroDivisionError``, and no completion.
_USES_OF_A_RAISING_CLASS = {
    "bare-call": "    Box(1)\n    return 3\n",
    "assign-and-read": "    a = Box(1)\n    assert a.n == 1\n",
    "assign-unread": "    a = Box(1)\n    return 3\n",
    "return-the-call": "    return Box(1)\n",
    "method-call": "    a = Box(1)\n    return a.get()\n",
}


@pytest.mark.parametrize("use", sorted(_USES_OF_A_RAISING_CLASS))
def test_a_function_that_calls_the_raising_class_halts_with_its_raise(use: str) -> None:
    """The class statement's halt is a face of the function that calls it.

    That it lands on the call, once per call, and not at the class statement,
    is #7794 and is not changed here.
    """
    completed, halts = _faces(
        _function(_ALWAYS_RAISES["only-field"], _USES_OF_A_RAISING_CLASS[use])
    )

    assert completed == 0
    assert len(halts) == 1 and "ZeroDivisionError" in halts[0]


def test_a_read_through_the_raising_class_call_is_its_raise() -> None:
    """``assert Box(1).n == 1``: the call is the assert's own operand, so the
    assert is that effect, not a completion and not an ``AssertionError``."""
    from sugar_lift_py_tests.outcome import Incomplete

    outcome = _function(_ALWAYS_RAISES["only-field"], "    assert Box(1).n == 1\n")

    assert isinstance(outcome, Incomplete), outcome
    assert "ZeroDivisionError" in repr(outcome.effect)


def test_naming_the_raising_class_without_calling_it_completes() -> None:
    """``b = Box`` calls nothing, so the function has no raise of its own:
    Python raised at the class statement, when the module ran.  Nothing
    reduces the module block today, so that raise has no row (#7794)."""
    completed, halts = _faces(
        _function(_ALWAYS_RAISES["only-field"], "    b = Box\n    return 3\n")
    )

    assert (completed, halts) == (1, ())


# ---------------------------------------------------------------------------
# The second dropped halt: a class statement reduced with no context.
# ``tree_enumerate.function_universe_outcome`` (an ``__init__`` universe) and
# ``Assign._constructed_floor_value`` reduce it that way.
# ---------------------------------------------------------------------------

_MAY_RAISE_CALLS = ['int("x")', "float(S)", "os.getcwd()", "frozenset(S)"]


@pytest.mark.parametrize("with_context", [False, True], ids=["no-ctx", "root-ctx"])
@pytest.mark.parametrize("call", _MAY_RAISE_CALLS)
def test_a_field_call_that_may_raise_is_two_faces_with_or_without_a_context(
    call: str, with_context: bool
) -> None:
    completed, halts = _faces(
        _class_statement(f"    limit = {call}\n", with_context=with_context)
    )

    assert completed == 1
    assert len(halts) == 1


def test_the_initializer_universe_of_a_may_raise_class_refuses_by_name() -> None:
    """An ``__init__`` universe reduces its class statement with no context
    and wants one completion.  With ``limit = int("x")`` it used to get one,
    the halt dropped; it now gets two faces and refuses by name."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes
    from sugar_source_tree.panic import SugarNotWritten

    tree = _tree(_PRELUDE + 'class Box:\n    limit = int("x")\n' + _INIT)
    (initializer,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "__init__"
    )

    with pytest.raises(SugarNotWritten, match="function_universe_outcome"):
        function_universe_outcome(initializer)


# ---------------------------------------------------------------------------
# Unchanged: faces that were already carried, and the refusals that stay.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "halted"),
    [
        ('    limit = os.environ["L"]\n', 1),
        ('    limit = int(os.environ["L"])\n', 2),
        ('    a = os.environ["A"]\n    b = os.environ["B"]\n', 2),
        # ``a = b = e`` evaluates ``e`` once.
        ('    a = b = os.environ["A"]\n', 1),
        ("    limit = 3\n", 0),
        ("    pass\n", 0),
    ],
    ids=["subscript", "call-of-subscript", "two-fields", "chained", "plain", "empty"],
)
def test_a_field_that_may_raise_keeps_its_faces(body: str, halted: int) -> None:
    completed, halts = _faces(_class_statement(body, with_context=True))

    assert completed == 1
    assert len(halts) == halted


def test_the_class_holds_each_field_value_in_source_order() -> None:
    from sugar_lift_py_tests.outcome import Complete

    outcome = _class_statement(
        "    a = b = 1\n    c: int = 2\n    if True:\n        d = 3\n    else:\n        e = 4\n",
        with_context=True,
    )

    assert isinstance(outcome, Complete), outcome
    fields = outcome.value.class_fields
    assert [field.name for field in fields] == ["a", "b", "c", "d"]
    assert fields[0].value is fields[1].value


def test_a_class_conditional_that_is_not_ground_still_refuses() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="not a ground bool literal"):
        _class_statement("    if FLAG:\n        limit = 1\n", with_context=True)
    # Also when a field before it always raises: the refusal is not traded
    # for the halt.
    with pytest.raises(SugarNotWritten, match="not a ground bool literal"):
        _class_statement(
            "    limit = 1 // 0\n    if FLAG:\n        a = 1\n", with_context=True
        )


def test_a_field_with_several_completed_values_still_refuses() -> None:
    """Left: lifting this refusal builds one class per value, a completion
    where there is a refusal.  It is its own change."""
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten, match="class field limit did not construct completely"
    ):
        _class_statement("    limit = FLAG or int(FLAG)\n", with_context=True)


# ---------------------------------------------------------------------------
# #7799's other half: a class body that reads an undefined name.  Python
# raises ``NameError`` at the class statement and the class is never bound.
# The read is a ``NameError`` halt (``NameSugar``, #7854); the field goes
# through the assignment routine, so that halt is the class statement's.
# ---------------------------------------------------------------------------

_READS_AN_UNDEFINED_NAME = {
    "only-field": "    limit = nope\n",
    "second-of-three": "    a = 1\n    limit = nope\n    b = 2\n",
    "annotated": "    limit: int = nope\n",
    # A later field does not run after the halt: no ``os.environ`` face.
    "before-a-may-raise": '    limit = nope\n    a = int(os.environ["L"])\n',
}


def _halt_effects(outcome) -> tuple[object, ...]:
    from sugar_lift_py_tests.outcome import ExitSet, Halted, Incomplete

    if isinstance(outcome, Incomplete):
        return (outcome.effect,)
    if isinstance(outcome, ExitSet):
        return tuple(face.effect for face in outcome.exits if isinstance(face, Halted))
    return ()


def _the_name_error(outcome):
    from sugar_lift_py_tests.effect import NameErrorEffect

    (effect,) = (
        effect
        for effect in _halt_effects(outcome)
        if isinstance(effect, NameErrorEffect)
    )
    return effect


@pytest.mark.parametrize("with_context", [False, True], ids=["no-ctx", "root-ctx"])
@pytest.mark.parametrize("shape", sorted(_READS_AN_UNDEFINED_NAME))
def test_a_class_body_that_reads_an_undefined_name_halts_with_name_error(
    shape: str, with_context: bool
) -> None:
    outcome = _class_statement(
        _READS_AN_UNDEFINED_NAME[shape], with_context=with_context
    )
    completed, halts = _faces(outcome)

    assert completed == 0
    effect = _the_name_error(outcome)
    assert effect.exception_name == "NameError"
    assert effect.name == "nope"
    if shape == "before-a-may-raise":
        # The field after the halt never ran: the statement has that one halt.
        assert len(halts) == 1


@pytest.mark.parametrize("use", sorted(_USES_OF_A_RAISING_CLASS))
def test_a_function_that_calls_a_class_reading_an_undefined_name_halts(
    use: str,
) -> None:
    outcome = _function(
        _READS_AN_UNDEFINED_NAME["only-field"], _USES_OF_A_RAISING_CLASS[use]
    )
    completed, halts = _faces(outcome)

    assert completed == 0
    assert len(halts) == 1
    assert _the_name_error(outcome).name == "nope"


# ---------------------------------------------------------------------------
# The twin, through the real solver.  One thing differs: the class field.
#
# Truthful: the class exists, the call completes, the assert after it holds:
# ``sat``.  Lying: the class body raises, so the call raises and the assert
# after it is never reached.  Before this change the solver answered ``sat``
# to the lying half too.
#
# What the lying half gets today is no verdict, not ``unsat``: the function's
# only arm is halted at the call, an assert no arm evaluated has no row, and
# halted arms of a reduction are not emitted (#7766).  The harness reports
# that as "no assertion rows".  The ``unsat`` this twin should end in is the
# expected-red test below.
# ---------------------------------------------------------------------------

_TWIN = (
    "class Box:\n"
    "    limit = {field}\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    Box()\n"
    "    assert 1 == 1\n"
)


def test_an_assert_after_a_call_of_a_class_that_exists_is_sat(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(field="3"))

    assert truthful.verdict == "sat"


def test_an_assert_after_a_call_of_a_raising_class_is_not_sat(tmp_path: Path) -> None:
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(field="1 // 0"))

    with pytest.raises(WitnessPipelineError, match="no assertion rows"):
        lying.verdict


@pytest.mark.xfail(
    strict=True,
    raises=WitnessPipelineError,
    reason=(
        "the lying half is not refuted: the function's only arm is halted at "
        "the class call, the assert after it has no row, and halted arms of a "
        "reduction are not emitted, so there is no verdict where there should "
        "be unsat (#7766)"
    ),
)
def test_an_assert_after_a_call_of_a_raising_class_is_unsat(tmp_path: Path) -> None:
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(field="1 // 0"))

    assert lying.verdict == "unsat"


# #7799's own program: the class has an ``__init__``.  Its universe is built
# over the class statement (``tree_enumerate.function_universe_outcome``), so
# when the statement halts, mint refuses the file by name.
_TWIN_WITH_INITIALIZER = (
    "class Box:\n"
    "    limit = {field}\n"
    "\n"
    "    def __init__(self, n):\n"
    "        self.n = n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    a = Box(1)\n"
    "    assert a.n == 1\n"
)


def test_a_field_of_an_object_of_a_class_that_exists_is_sat(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "t", _TWIN_WITH_INITIALIZER.format(field="3")
    )

    assert truthful.verdict == "sat"


def test_a_raising_class_with_an_initializer_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(WitnessPipelineError, match="function_universe_outcome"):
        run_source_through_real_solver(
            tmp_path / "l", _TWIN_WITH_INITIALIZER.format(field="1 // 0")
        )
