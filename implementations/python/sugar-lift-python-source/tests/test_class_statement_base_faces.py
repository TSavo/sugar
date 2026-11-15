"""A class statement carries every face of every base expression (#7755).

Python evaluates the base expressions of a class statement, in order, before
the class body runs.  If evaluating a base raises, the class statement raises
and no class is created.  So the bases are an operand fold: every raise face
of every base is a raise face of the statement; a base with no completion
leaves the statement with no completion; a base with several completions
builds the class once per completion, each with the base it was built over.
A base that cannot be built refuses by name.

The solver twins run real test source through lift, mint and ``sugar prove
--z3``.  The object-level tests pin the mechanism in the class statement and
in the cited C-type subscript.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.ir import atomic, str_const, ctor
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import ExitSet, complement_guard
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.panic import SugarNotWritten

from test_contextlib_suppress_source_exit_faces import _corpus, _open


# ---------------------------------------------------------------------------
# Solver twins: the code after a class statement whose base always raises
# never runs.
# ---------------------------------------------------------------------------

_BASE_TWIN = (
    "class Base:\n"
    "    pass\n"
    "\n"
    "def make_base():\n"
    "{make_body}"
    "\n"
    "def test_class_statement_base():\n"
    "    reached = 0\n"
    "    try:\n"
    "        class Derived(make_base()):\n"
    "            pass\n"
    "        reached = 1\n"
    "    except ValueError:\n"
    "        reached = 2\n"
    "    assert reached == 1\n"
)


def test_a_base_that_always_raises_raises_the_class_statement(tmp_path: Path):
    """Twin: the one difference is whether evaluating the base raises.

    Truthful: the base completes, the statement after the class runs, and
    ``reached == 1`` holds (``sat``).  Lying: the same test whose base always
    raises ``ValueError``; the class statement raises it, the handler sets
    ``reached = 2``, and the claim is refuted (``unsat``).  With the base's
    raise dropped (the defect) the lying source claimed ``reached == 1`` too.
    """
    from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        _BASE_TWIN.format(make_body="    return Base\n"),
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        _BASE_TWIN.format(make_body="    raise ValueError('no base')\n"),
    )
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


_FACTORY_TWIN = (
    "from contextlib import nullcontext\n"
    "\n"
    "def manager_factory(flag):\n"
    "    if flag:\n"
    "        return nullcontext()\n"
    "    return nullcontext(1)\n"
    "\n"
    "def test_manager_from_a_two_return_factory():\n"
    "    reached = 0\n"
    "    with manager_factory(True):\n"
    "        reached = 1\n"
    "    assert reached == {expected}\n"
)


def test_a_manager_from_a_factory_with_two_guarded_returns(tmp_path: Path):
    """Twin for the class statements behind ``contextlib.nullcontext``.

    ``nullcontext``'s bases are ``AbstractContextManager`` and
    ``AbstractAsyncContextManager``, whose own base is ``abc.ABC``.  At
    1436229a8 the class statement carried a base's halt, and ``abc.ABC`` read
    inside the contextlib frame as an undecided module attribute
    (``UnknownAttribute:abc.ABC``), so building ``nullcontext`` had raise faces
    no source has, and the factory refused as ``non-manager-result``.  Read
    through its import receipt (579f8b74c) ``abc.ABC`` is the authenticated
    member and completes; the class statement still carries every base face.

    Through real mint the project's own files are the only source the kit
    reads (``lift_rpc``: the walk session enrolls the project file roster),
    and no proof for ``contextlib`` is staged in ``.sugar/imports/``.  So
    ``nullcontext()`` is an edge nothing answers: the proof owes it as an
    ``undecided`` member (step 8), the manager is cited, and the claim after
    the ``with`` stands on its completing face.  Truthful: the body ran, which
    nothing refutes and nothing proves while the call is owed (``open``; this
    twin states "not bridged" and reads ``sat`` when a proof answering
    ``contextlib.nullcontext`` is staged).  Lying: the same test claiming the
    body did not run, false on every face that reaches the assert
    (``unsat``).
    """
    from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", _FACTORY_TWIN.format(expected=1)
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying", _FACTORY_TWIN.format(expected=0)
    )
    assert truthful.verdict == "open"
    assert truthful.prove_doc["owed"] >= 1
    assert lying.verdict == "unsat"


# ---------------------------------------------------------------------------
# Mechanism: the class statement's base fold.
# ---------------------------------------------------------------------------

_PRELUDE = (
    "class A:\n"
    "    def __init__(self):\n"
    "        self.a = 1\n"
    "class B:\n"
    "    def __init__(self):\n"
    "        self.b = 1\n"
    "def boom():\n"
    "    raise ValueError('x')\n"
)


def _class_sugar(tmp_path: Path, source: str, name: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tree = _open(_corpus(tmp_path, _PRELUDE + source))
    node = next(n for n in tree.nodes() if isinstance(n, ClassDef) and n.name == name)
    return node.sugar()


_W = "class W(A):\n    pass\n"


def _w_and_classes(tmp_path: Path, *names: str):
    """``W``'s class sugar and the class value of each prelude class in
    ``names``, all read off ONE opened source.

    The ``__init__`` a call of a class runs is the one the class-namespace
    lookup selects over the statement's own source (``ClassDef.
    initializer_entry``), found among the class value and its bases by the
    class statement's occurrence (``ClassDefinitionValue.
    class_value_of_statement``: file, source CID, span).  A base value built
    from another source text is a different occurrence, which no lookup over
    ``W``'s source names; the base ``W`` is built over here is the class its
    own source binds."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    tree = _open(_corpus(tmp_path, _PRELUDE + _W))

    def sugar_of(name: str):
        node = next(
            n for n in tree.nodes() if isinstance(n, ClassDef) and n.name == name
        )
        return node.sugar()

    values = []
    for name in names:
        value = sugar_of(name).desugar().completed_value()
        assert isinstance(value, ClassDefinitionValue)
        values.append(value)
    return sugar_of("W"), tuple(values)


@dataclasses.dataclass(frozen=True)
class _BaseOperand:
    """A base expression whose evaluation yields exactly ``outcome``."""

    outcome: object
    class_definition_cid: str = "stub-base"

    def desugar(self, ctx=None):
        del ctx
        # A refusal is a ``LifterRefusal``, a ``BaseException``: it is never
        # an ``Exception`` a handler for ordinary errors could swallow.
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _over(sugar, outcome):
    return dataclasses.replace(sugar, base_sugars=(_BaseOperand(outcome),))


def _with_base(tmp_path: Path, outcome):
    return _over(_class_sugar(tmp_path, _W, "W"), outcome)


def _halt(owner: str):
    return UndeterminedRaiseEffect(
        blame="w.py:1:0", occurrence="k", producer_node_owner=owner, site="w.py:1:0"
    )


def _atom(name: str):
    return atomic("test:base.completes", [ctor("test:base", (str_const(name),))])


def _rows(outcome):
    rows = []
    for face in outcome.exits:
        if isinstance(face, Halted):
            rows.append(("halt", getattr(face.effect, "producer_node_owner", None)))
        else:
            rows.append(
                (
                    "class",
                    tuple(base.class_name for base in face.value.base_classes),
                    getattr(face.value.initializer, "name", None),
                )
            )
    return sorted(rows, key=repr)


def test_a_base_with_no_completion_leaves_no_class(tmp_path: Path):
    """Truthful: a base that only halts; the statement is that halt alone."""
    completes = _atom("never")
    only_halt = ExitSet((Halted(complement_guard(completes), _halt("base"), None),))
    assert _rows(_with_base(tmp_path, only_halt).desugar()) == [("halt", "base")]


def test_a_base_with_one_completion_builds_the_class_over_it(tmp_path: Path):
    """Lying twin of the above: the same base given its completed face.

    The class exists on that face, built over the base it completed with
    (so it inherits ``A.__init__``), and the halt is still a face.
    """
    completes = _atom("once")
    w, (value,) = _w_and_classes(tmp_path, "A")
    two_faced = ExitSet(
        (
            Completed(completes, value),
            Halted(complement_guard(completes), _halt("base"), None),
        )
    )
    assert _rows(_over(w, two_faced).desugar()) == [
        ("class", ("A",), "__init__"),
        ("halt", "base"),
    ]


def test_a_base_with_several_completions_builds_one_class_per_completion(
    tmp_path: Path,
):
    """One class per completed face of the base, each built over the base it
    completed with.  ``W``'s source names ``A``: over ``A`` the class runs
    ``A.__init__``, the ``__init__`` the lookup over its source selects.
    Over ``B``, a class its source does not name, that lookup finds no class
    among the bases it was built over, so no source ``__init__`` is assumed
    for it (``ClassDefinitionValue.initializer_class``): the class is built
    over ``B`` all the same."""
    completes = _atom("which")
    w, (a, b) = _w_and_classes(tmp_path, "A", "B")
    two_classes = ExitSet(
        (
            Completed(completes, a),
            Completed(complement_guard(completes), b),
        )
    )
    assert _rows(_over(w, two_classes).desugar()) == [
        ("class", ("A",), "__init__"),
        ("class", ("B",), None),
    ]


def test_only_the_builtin_type_binding_is_retained_as_a_base(tmp_path: Path):
    """``type`` is retained as a base by the object the builtin namespace
    binds, never the spelling (#7757).  A source ``class type: pass`` seeds
    a ``ClassValue`` named ``type`` equal field-for-field to the builtin's
    (``module_class_value``); built over it, the class has no base, as for
    any other generic class value.  Built over the builtin, it keeps it."""
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_type_class,
    )

    builtin = builtin_type_class()
    shadow = ClassValue(name="type", bases=(), record=BlockValue(()))
    assert shadow is not builtin

    over_builtin = _with_base(tmp_path / "builtin", ExitSet.completed(builtin))
    (kept,) = over_builtin.desugar().completed_value().base_classes
    assert kept is builtin

    over_shadow = _with_base(tmp_path / "shadow", ExitSet.completed(shadow))
    assert over_shadow.desugar().completed_value().base_classes == ()


def test_a_source_base_that_always_raises_is_the_statements_raise(tmp_path: Path):
    """The class body never runs after a base that raised: its own raise is
    not reached, and the base's raise is the statement's only face.

    The base raises through an operation the reduction decides (``1 // 0``,
    a ground ``ZeroDivisionError``).  A same-file call (``boom()``) is its
    coordinate and edge since #7757 step 6, two-faced at the reduction
    whatever ``boom`` runs: its halt is decided at prove, never here, so it
    cannot state "the base always raises" at this level."""
    class_sugar = _class_sugar(tmp_path, "class W(1 // 0):\n    x = 1 // 0\n", "W")
    outcome = class_sugar.desugar()
    assert not any(isinstance(face, Completed) for face in outcome.exits)
    assert [type(face.effect).__name__ for face in outcome.exits] == ["RaiseEffect"]


def test_a_base_refusal_is_never_swallowed(tmp_path: Path):
    """The ``ImportMemberValue.subscript`` refusal used to be caught and the
    base dropped.  It is still raised (a subscript with no site, or a key
    with no term), so it now refuses the class statement by name."""
    refusal = SugarNotWritten(
        blame="m.py:1:0",
        owner="ImportMemberValue.subscript",
        observed="undecided receiver runtime type or index semantics",
        requested="a source-authenticated subscript success or exceptional exit",
        fix="carry receiver-type and index testimony to its native floor",
    )
    with pytest.raises(SugarNotWritten) as raised:
        _with_base(tmp_path, refusal).desugar()
    assert raised.value is refusal


class _KeyWithNoTerm:
    def to_term(self, *, owner):
        raise SugarNotWritten(
            blame="m.py:1:0",
            owner=owner,
            observed="a key with no term",
            requested="a term",
            fix="none: test key",
        )


def test_import_member_subscript_refusal_is_still_reachable():
    """Why the carve-out was live: ``ImportMemberValue.subscript`` over a key
    with no term still refuses by that owner (#7680 made only the termed,
    sited subscript two-faced), so a class base built from it was silently
    dropped."""
    from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue

    member = ImportMemberValue.__new__(ImportMemberValue)
    for name, value in (
        ("qualified_name", "typing.Generic"),
        ("source_cid", "s"),
        ("import_binding_cid", "b"),
        ("use_cid", "u"),
        ("exported_member_path", ("Generic",)),
    ):
        object.__setattr__(member, name, value)
    with pytest.raises(SugarNotWritten) as raised:
        member.subscript(_KeyWithNoTerm(), "m.py:1:0")
    # The key's own refusal propagates as itself; it is not rewritten into an
    # undecided-receiver refusal.
    assert raised.value.owner == "ImportMemberValue.subscript"
    assert raised.value.observed == "a key with no term"
