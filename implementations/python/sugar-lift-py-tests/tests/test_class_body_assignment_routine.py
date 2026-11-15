"""Plan row 7 (steps 5 and 6), map item 1: a class field is an assignment.

A class body used to sequence its own fields.  It asked of each right-hand
side only "is it one completed value" and stored the value, so ``limit = 1 // 0``
(a completion that carried the raise as data) became the field's value and
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

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

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
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is not None:
        assert value.follow_rest().continues, outcome
        return 1, ()
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


# What a function that uses the raising class reduces to.
_USES_OF_A_RAISING_CLASS = {
    "bare-call": "    Box(1)\n    return 3\n",
    "assign-and-read": "    a = Box(1)\n    assert a.n == 1\n",
    "assign-unread": "    a = Box(1)\n    return 3\n",
    "return-the-call": "    return Box(1)\n",
    "method-call": "    a = Box(1)\n    return a.get()\n",
}


def _refused_for_the_unbound_class(reduce) -> None:
    """``reduce()`` reads ``Box`` through its class statement's key, and
    nothing bound it: the module's one run completed on no arm (its class
    statement halted), so the read is refused by name, the one refusal of a
    read of an unbound key.  The class statement is never reduced again for
    the reader, so its halt is the module run's, never a face of a function
    that calls the class (#7757 item 21; before, #7794 landed it on each
    call)."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="read of `Box`.*unbound"):
        reduce()


@pytest.mark.parametrize("use", sorted(_USES_OF_A_RAISING_CLASS))
def test_a_function_that_calls_the_raising_class_is_undecided_by_name(
    use: str,
) -> None:
    """The class statement halts where it runs, in the module's run.  A
    function that calls the class reads the class that run bound, and it
    bound none: the function is refused by name (undecided), never handed
    the statement's halt by a second reduction of it."""
    _refused_for_the_unbound_class(
        lambda: _function(
            _ALWAYS_RAISES["only-field"], _USES_OF_A_RAISING_CLASS[use]
        )
    )


def test_a_read_through_the_raising_class_call_is_undecided_by_name() -> None:
    """``assert Box(1).n == 1``: the call's callee is the read of ``Box``,
    which no run bound."""
    _refused_for_the_unbound_class(
        lambda: _function(
            _ALWAYS_RAISES["only-field"], "    assert Box(1).n == 1\n"
        )
    )


def test_naming_the_raising_class_without_calling_it_completes() -> None:
    """``b = Box`` calls nothing, so the function has no raise of its own:
    Python raised at the class statement, when the module ran.  Nothing
    reduces the module block today, so that raise has no row (#7794)."""
    completed, halts = _faces(
        _function(_ALWAYS_RAISES["only-field"], "    b = Box\n    return 3\n")
    )

    assert (completed, halts) == (1, ())


# ---------------------------------------------------------------------------
# The second dropped halt: a class statement reduced with no context
# (the deleted ``Assign._constructed_floor_value`` reduced it that way).  An ``__init__``
# universe reads its class statement through the class call's one
# constructor, and carries the halt.
# ---------------------------------------------------------------------------

def _module_run(body: str):
    """THE module reduction (``tree_enumerate.owner_reduction`` with no owner)
    of the prelude and ``class Box`` with ``body``: the module body's one run,
    as an import runs it.

    A class body that reads a module global (``S``, ``FLAG``) reads the
    evaluation key the global's own statement bound, and only the block that
    ran that statement binds it.  The class statement reduced apart from its
    module is refused by name there (``EvaluationRefSugar._unbound``: "reduce
    the read after the statement in the block that ran it"), so such a body is
    read where Python runs it: in the module's run, after ``S = ...``."""
    from sugar_lift_py_tests.tree_enumerate import owner_reduction

    tree = _tree(_PRELUDE + "class Box:\n" + body + _INIT)
    return owner_reduction(None, tree).outcome


def _run_faces(outcome) -> tuple[int, int]:
    """(completed arms, halted arms) of a module run."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        sum(isinstance(face, Halted) for face in outcome.exits),
    )


_MAY_RAISE_CALLS = ["os.getcwd()"]
# A call over a module global that may raise: read in the module's run.
_MAY_RAISE_OVER_A_GLOBAL = ["float(S)", "frozenset(S)"]


@pytest.mark.parametrize("call", _MAY_RAISE_OVER_A_GLOBAL)
def test_a_field_call_over_a_module_global_that_may_raise_is_one_more_halt_of_the_run(
    call: str,
) -> None:
    """``S`` is what ``os.environ.get('S')`` returned, a value nothing here
    decides, so ``float(S)`` may raise: the class statement completes on one
    face and halts on one.  Twin of the same module with ``limit = 3``: the
    run completes on as many arms, and the may-raise field is exactly one more
    halted arm of it."""
    plain_completed, plain_halted = _run_faces(_module_run("    limit = 3\n"))
    completed, halted = _run_faces(_module_run(f"    limit = {call}\n"))

    assert plain_completed >= 1
    assert completed == plain_completed
    assert halted == plain_halted + 1


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


@pytest.mark.parametrize("with_context", [False, True], ids=["no-ctx", "root-ctx"])
def test_a_field_call_python_decides_to_raise_is_its_one_halt(
    with_context: bool,
) -> None:
    """``int("x")`` is a builtin over a ground operand: the builtin's own
    semantics decide it (``cpython_cited_fold``,
    ``test_builtin_call_may_raise_by_value``), and Python raises
    ``ValueError``, always.  It is not a call that may raise: the class
    statement halts with that one ``ValueError`` and no class exists, with a
    context or without one, exactly as for ``limit = 1 // 0``."""
    outcome = _class_statement('    limit = int("x")\n', with_context=with_context)
    completed, halts = _faces(outcome)

    assert completed == 0
    assert len(halts) == 1
    assert [
        getattr(effect, "exception_name", None) for effect in _halt_effects(outcome)
    ] == ["ValueError"]


def _initializer_universe(source: str):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    tree = _tree(_PRELUDE + source)
    (initializer,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "__init__"
    )
    return function_universe_outcome(initializer)


def test_the_initializer_universe_of_a_may_raise_class_runs_on_the_class_it_built() -> (
    None
):
    """An ``__init__`` universe runs on the receiver its class call makes
    (``ClassConstructorBodySugar.enter_initializer``), on the class its
    statement bound in the module's one run.  With a field call that may
    raise (``limit = os.getcwd()``) that run binds the class on its
    completed arm, and the statement's halt is the run's, not this
    universe's: the universe is one completed face."""
    completed, halts = _faces(
        _initializer_universe("class Box:\n    limit = os.getcwd()\n" + _INIT)
    )

    assert (completed, halts) == (1, ())


def test_the_initializer_universe_of_a_decided_raising_call_is_undecided() -> None:
    """``limit = int("x")`` always raises ``ValueError`` (a builtin over a
    ground operand, decided): the module's run bound no class, so the
    ``__init__`` universe has no class to run on and is refused by name, as
    for ``limit = 1 // 0`` below."""
    _refused_for_the_unbound_class(
        lambda: _initializer_universe('class Box:\n    limit = int("x")\n' + _INIT)
    )


def test_the_initializer_universe_of_a_raising_class_is_undecided() -> None:
    """``limit = 1 // 0``: the module's run bound no class, so ``__init__``
    has none to run on; its universe is refused by name, never the class
    statement's halt read off a second reduction of it."""
    _refused_for_the_unbound_class(
        lambda: _initializer_universe(
            "class Box:\n" + _ALWAYS_RAISES["only-field"] + _INIT
        )
    )


def test_the_initializer_universe_under_an_unrun_source_new_refuses() -> None:
    """``Box(n)`` runs ``Box.__new__`` before ``__init__``; the class call
    refuses a source ``__new__`` it does not run, and the ``__init__``
    universe gets the same refusal from the same constructor."""
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten, match="__new__ is source the class call does not run"
    ):
        _initializer_universe(
            "class Box:\n"
            "    def __new__(cls, n):\n"
            "        return object.__new__(cls)\n" + _INIT
        )


# ---------------------------------------------------------------------------
# Unchanged: faces that were already carried, and the refusals that stay.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "halted"),
    [
        # Each ``os.environ`` is a dotted read off an imported module, which
        # may raise (the member may be absent; no module's namespace is
        # held): one halt of its own, before the subscript's.
        ('    limit = os.environ["L"]\n', 2),
        ('    limit = int(os.environ["L"])\n', 3),
        ('    a = os.environ["A"]\n    b = os.environ["B"]\n', 4),
        # ``a = b = e`` evaluates ``e`` once.
        ('    a = b = os.environ["A"]\n', 2),
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
    outcome = _class_statement(
        "    a = b = 1\n    c: int = 2\n    if True:\n        d = 3\n    else:\n        e = 4\n",
        with_context=True,
    )

    assert outcome.completed_value() is not None, outcome
    fields = outcome.completed_value().class_fields
    assert [field.name for field in fields] == ["a", "b", "c", "d"]
    assert fields[0].value is fields[1].value


def test_a_class_conditional_that_is_not_ground_still_refuses() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    # ``FLAG`` is a module global: the class body reads it in the module's
    # run (``_module_run``), where its statement bound it.
    with pytest.raises(SugarNotWritten, match="not a ground bool literal"):
        _module_run("    if FLAG:\n        limit = 1\n")
    # Also when a field before it always raises: the refusal is not traded
    # for the halt.
    with pytest.raises(SugarNotWritten, match="not a ground bool literal"):
        _module_run("    limit = 1 // 0\n    if FLAG:\n        a = 1\n")


def test_a_field_with_several_completed_values_still_refuses() -> None:
    """Left: lifting this refusal builds one class per value, a completion
    where there is a refusal.  It is its own change."""
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten, match="class field limit did not construct completely"
    ):
        _module_run("    limit = FLAG or int(FLAG)\n")


def test_a_body_that_did_not_run_to_its_end_builds_no_class() -> None:
    """A completed class body has one form, its record.  The assignment
    routine hands a value whose rest does not run back as it is; the class
    statement used to take any such value as the class's fields and complete
    (the path ``limit = 1 // 0`` took while a raise was a completed value,
    #7799).  It is no class body: no class is built from it, by name."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_source_tree import nodes
    from sugar_source_tree.panic import SugarNotWritten

    tree = _tree(_PRELUDE + "class Box:\n    limit = 3\n" + _INIT)
    (box,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.ClassDef) and node.name == "Box"
    )
    stopped = ExitSet.completed(BlockValue((), can_fall_through=False))
    assert not stopped.completed_value().follow_rest().continues

    with pytest.raises(SugarNotWritten, match="not the body's record"):
        box.sugar()._construct((), lambda: stopped)


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
    from sugar_lift_py_tests.outcome import ExitSet, Halted

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
def test_a_function_that_calls_a_class_reading_an_undefined_name_is_undecided(
    use: str,
) -> None:
    """The ``NameError`` is the class statement's, in the module's run: that
    run bound no class, so the function that calls it is refused by name."""
    _refused_for_the_unbound_class(
        lambda: _function(
            _READS_AN_UNDEFINED_NAME["only-field"], _USES_OF_A_RAISING_CLASS[use]
        )
    )


# ---------------------------------------------------------------------------
# The twin, through the real solver.  One thing differs: the class field.
#
# Truthful: the class exists, the call completes, the assert after it holds:
# ``sat``.  Lying: the class body raises, so the call raises and the assert
# after it is never reached.  Before this change the solver answered ``sat``
# to the lying half too.
#
# The function's only arm is halted at the call, so no arm completes and the
# assert no arm reached states the halted arm's guard negated: the halt is
# under truth, so the row is ``false`` and the lying half reads ``unsat``
# (#7766).  The test certainly raises, so it fails.
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


def test_an_assert_after_a_call_of_a_raising_class_is_unsat(tmp_path: Path) -> None:
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(field="1 // 0"))

    assert lying.verdict == "unsat"


# #7799's own program: the class has an ``__init__``.  Its universe runs on the
# receiver the class call makes (``tree_enumerate.function_universe_outcome``),
# so when the statement halts, the universe is that halt, as the call in
# ``test_box`` is: no arm reaches the assert, and its row states the halt.
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


def test_a_raising_class_with_an_initializer_is_unsat(tmp_path: Path) -> None:
    lying = run_source_through_real_solver(
        tmp_path / "l", _TWIN_WITH_INITIALIZER.format(field="1 // 0")
    )

    assert lying.verdict == "unsat"
