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
    Truthful: the body ran (``sat``).  Lying: the same test claiming it did
    not (``unsat``).
    """
    from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", _FACTORY_TWIN.format(expected=1)
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying", _FACTORY_TWIN.format(expected=0)
    )
    assert truthful.verdict == "sat"
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


def _class_value(tmp_path: Path, name: str):
    sugar = _class_sugar(tmp_path / name, "", name)
    value = sugar.desugar().completed_value()
    assert isinstance(value, ClassDefinitionValue)
    return value


@dataclasses.dataclass(frozen=True)
class _BaseOperand:
    """A base expression whose evaluation yields exactly ``outcome``."""

    outcome: object
    class_definition_cid: str = "stub-base"

    def desugar(self, ctx=None):
        del ctx
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _with_base(tmp_path: Path, outcome):
    sugar = _class_sugar(tmp_path, "class W(A):\n    pass\n", "W")
    return dataclasses.replace(sugar, base_sugars=(_BaseOperand(outcome),))


def _halt(owner: str):
    return UndeterminedRaiseEffect(blame="w.py:1:0", occurrence="k", producer_node_owner=owner)


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
    value = _class_value(tmp_path, "A")
    two_faced = ExitSet(
        (
            Completed(completes, value),
            Halted(complement_guard(completes), _halt("base"), None),
        )
    )
    assert _rows(_with_base(tmp_path / "w", two_faced).desugar()) == [
        ("class", ("A",), "__init__"),
        ("halt", "base"),
    ]


def test_a_base_with_several_completions_builds_one_class_per_completion(
    tmp_path: Path,
):
    completes = _atom("which")
    two_classes = ExitSet(
        (
            Completed(completes, _class_value(tmp_path / "a", "A")),
            Completed(complement_guard(completes), _class_value(tmp_path / "b", "B")),
        )
    )
    assert _rows(_with_base(tmp_path / "w", two_classes).desugar()) == [
        ("class", ("A",), "__init__"),
        ("class", ("B",), "__init__"),
    ]


def test_a_source_base_that_always_raises_is_the_statements_raise(tmp_path: Path):
    """The class body never runs after a base that raised: its refusal is
    not reached, and the base's raise is the statement's only face."""
    class_sugar = _class_sugar(tmp_path, "class W(boom()):\n    x = boom()\n", "W")
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
    assert raised.value.owner == "ImportMemberValue.subscript"
