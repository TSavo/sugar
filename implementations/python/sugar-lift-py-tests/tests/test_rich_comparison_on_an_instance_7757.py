"""A rich comparison on a source-class instance is the one unanswered call
of its dunder wherever its method order is not decided here (#7757 H13).

Before, three arms refused real Python by name (construction panics):

- ``ObjectValue._source_rich_comparison``: ``self == other`` (and each
  ordering) whose right operand is a formal, an instance of another class,
  or whose ``__eq__`` is a class-field value (``__eq__ = _cmp``);
- ``FloorValue.equals``: ``1 == obj``, the right operand's reflection;
- ``ComparisonOpSugar._apply``: ``self != other`` on any class whose
  ``__ne__`` the lookup did not decide absent.

Now each is the existing ``ObjectValue.unanswered_method_call`` of the
dunder Python's order calls: the left operand's (``__ne__`` exactly as
``__eq__``), or the right operand's reflection, called with the operands
swapped.  Two faces, owed, the halt kept, the value the call's own result
coordinate.  Which member answers is prove's dispatch walk.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from frame_fresh import FRAME_FRESH
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)


@dataclass(frozen=True)
class _FixedSugar(ConstructedTermSugar):
    """An operand that completes with ``value``."""

    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    def to_term(self, *, owner: str):
        return TermValue(0).to_term(owner=owner)


# ---------------------------------------------------------------------------
# Twins: mint + prove, each comparison inside ``__init__``
# ---------------------------------------------------------------------------

_TEST = "def test_f():\n    assert {claim}\n"

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # ``self == other`` with ``other`` a formal: ``P.__eq__(self, 1)``.
    "self-equals-a-formal": (
        "class P:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __init__(self, other):\n"
        "        self.same = self == other\n"
        "\n"
        "\n" + _TEST,
        "P(1).same == True",
        "P(1).same == False",
    ),
    # ``1 == self``: ``int.__eq__`` answers ``NotImplemented``, then the
    # reflection ``P.__eq__(self, 1)`` runs.
    "literal-equals-self-reflects": (
        "class P:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __init__(self):\n"
        "        self.same = 1 == self\n"
        "\n"
        "\n" + _TEST,
        "P().same == True",
        "P().same == False",
    ),
    # ``self != other`` with only ``__eq__`` defined: ``object.__ne__``
    # negates ``P.__eq__``.
    "self-not-equals-with-eq-defined": (
        "class P:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __init__(self, other):\n"
        "        self.diff = self != other\n"
        "\n"
        "\n" + _TEST,
        "P(1).diff == False",
        "P(1).diff == True",
    ),
    # ``self != other`` with ``__ne__`` defined: ``P.__ne__`` runs, not a
    # negated ``__eq__``.
    "self-not-equals-with-ne-defined": (
        "class P:\n"
        "    def __eq__(self, other):\n"
        "        return False\n"
        "    def __ne__(self, other):\n"
        "        return False\n"
        "    def __init__(self, other):\n"
        "        self.diff = self != other\n"
        "\n"
        "\n" + _TEST,
        "P(1).diff == False",
        "P(1).diff == True",
    ),
    # An undecided base: whether ``__ne__`` is the base's is not decided by
    # the lookup.
    "undecided-base-not-equals": (
        "from abc import ABC\n"
        "\n"
        "\n"
        "class P(ABC):\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __init__(self, other):\n"
        "        self.diff = self != other\n"
        "\n"
        "\n" + _TEST,
        "P(1).diff == False",
        "P(1).diff == True",
    ),
    "undecided-base-literal-equals-self": (
        "from abc import ABC\n"
        "\n"
        "\n"
        "class P(ABC):\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "    def __init__(self):\n"
        "        self.same = 1 == self\n"
        "\n"
        "\n" + _TEST,
        "P().same == True",
        "P().same == False",
    ),
    # An ordering across two classes: ``P.__lt__(self, Q())``.
    "self-less-than-another-class": (
        "class Q:\n"
        "    pass\n"
        "\n"
        "\n"
        "class P:\n"
        "    def __lt__(self, other):\n"
        "        return True\n"
        "    def __init__(self):\n"
        "        self.less = self < Q()\n"
        "\n"
        "\n" + _TEST,
        "P().less == True",
        "P().less == False",
    ),
    # A class-field ``__eq__``: ``_cmp`` bound as the method.
    "class-field-eq": (
        "def _cmp(a, b):\n"
        "    return True\n"
        "\n"
        "\n"
        "class P:\n"
        "    __eq__ = _cmp\n"
        "    def __init__(self, other):\n"
        "        self.same = self == other\n"
        "\n"
        "\n" + _TEST,
        "P(1).same == True",
        "P(1).same == False",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_rich_comparison_never_admits_a_lie_nor_refutes_a_truth(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    native: dict = {}
    exec(text, native)
    if half == "truthful":
        native["test_f"]()
    else:
        with pytest.raises(AssertionError):
            native["test_f"]()
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


# ---------------------------------------------------------------------------
# Floor units: each former refusal is the unanswered call
# ---------------------------------------------------------------------------


def _receivers(source: str) -> dict:
    """A receiver of every module class of ``source``, by name, each made
    by a class call of the reading frame (``fresh_receiver``)."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "rich_comparison.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    ctx = ReduceContext.root(owner="test")
    receivers = {}
    for node in tree.root.body:
        if isinstance(node, ClassDef):
            value = node.sugar().desugar(ctx).completed_value()
            receivers[node.name] = value.fresh_receiver(
                f"{node.name}-receiver", allocation=FRAME_FRESH
            )
    return receivers


def _bare_receiver():
    """An instance whose class the one lookup does not decide: every
    member read on it is undecided (``class_member``)."""
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    return ObjectValue("Box", (), identity="receiver", allocation=FRAME_FRESH)


def _formal(name: str = "other"):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    return SymbolicValue(make_var(name))


def _unanswered(outcome, target: str, receiver, argument) -> None:
    """The one unanswered call ``target(receiver, argument)``: one completion
    under its ``completes`` atom, whose value is the call with no body
    applied, and one halt no exception names, owed -- never a refusal."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome import Completed, Halted

    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert isinstance(completed.value, CallSiteValue)
    assert completed.value.body is None
    assert completed.value.target_name == target
    assert completed.value.arg_values == (receiver, argument)
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == f"UnknownCallee:{target}"
    assert outcome.owed_items()


_EQ = (
    "class Box:\n"
    "    def __eq__(self, other):\n"
    "        return True\n"
    "    def __lt__(self, other):\n"
    "        return True\n"
    "    def __ne__(self, other):\n"
    "        return False\n"
    "class Other:\n"
    "    pass\n"
)


def test_self_equals_a_formal_is_the_unanswered_eq() -> None:
    box = _receivers(_EQ)["Box"]
    other = _formal()
    _unanswered(box.equals(other, "eq-site", None), "Box.__eq__", box, other)


def test_self_ordered_against_a_formal_is_the_unanswered_lt() -> None:
    box = _receivers(_EQ)["Box"]
    other = _formal()
    _unanswered(box.less_than(other, "lt-site", None), "Box.__lt__", box, other)


def test_self_equals_another_class_is_the_unanswered_eq() -> None:
    receivers = _receivers(_EQ)
    box, other = receivers["Box"], receivers["Other"]
    _unanswered(box.equals(other, "eq-site", None), "Box.__eq__", box, other)


def test_a_class_field_eq_is_the_unanswered_eq() -> None:
    source = "class Box:\n    __eq__ = lambda self, other: True\n"
    box = _receivers(source)["Box"]
    one = TermValue(1)
    _unanswered(box.equals(one, "eq-site", None), "Box.__eq__", box, one)


@pytest.mark.parametrize("decided", [True, False], ids=["decided", "undecided"])
def test_a_literal_equals_an_instance_is_the_reflected_unanswered_eq(
    decided: bool,
) -> None:
    box = _receivers(_EQ)["Box"] if decided else _bare_receiver()
    one = TermValue(1)
    # ``1 == box``: Python's order reflects to ``type(box).__eq__(box, 1)``.
    _unanswered(one.equals(box, "eq-site", None), "Box.__eq__", box, one)


def _comparison_site():
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import Name
    from sugar_source_tree.tree import SourceFile

    text = "a != b\n"
    tree = SourceFile((text, "not_equals.py", blake3_512_of(text.encode())))
    return next(node for node in tree.nodes() if isinstance(node, Name)).fragment


def _not_equals(left, right):
    from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar

    return ComparisonOpSugar(
        "NotEq", _FixedSugar(left), _FixedSugar(right), site=_comparison_site()
    ).desugar(None)


@pytest.mark.parametrize("decided", [True, False], ids=["decided", "undecided"])
def test_self_not_equals_a_formal_is_the_unanswered_ne(decided: bool) -> None:
    box = _receivers(_EQ)["Box"] if decided else _bare_receiver()
    other = _formal()
    _unanswered(_not_equals(box, other), "Box.__ne__", box, other)


@pytest.mark.parametrize("decided", [True, False], ids=["decided", "undecided"])
def test_a_formal_not_equals_an_instance_is_the_reflected_unanswered_ne(
    decided: bool,
) -> None:
    box = _receivers(_EQ)["Box"] if decided else _bare_receiver()
    other = _formal()
    # ``other != box``: the reflection ``type(box).__ne__(box, other)``.
    _unanswered(_not_equals(other, box), "Box.__ne__", box, other)


def test_not_equals_with_only_eq_keeps_the_unanswered_eq_halt() -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    source = "class Box:\n    def __eq__(self, other):\n        return True\n"
    box = _receivers(source)["Box"]
    outcome = _not_equals(box, _formal())
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert any(
        isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == "UnknownCallee:Box.__eq__"
        for face in halts
    ), outcome


def test_no_rich_comparison_refusal_remains() -> None:
    import inspect

    from sugar_lift_py_tests.floor import floor_value, object_value
    from sugar_lift_py_tests.sugar import comparison_op_sugar

    for module, phrase in (
        (object_value, "method order is not authenticated"),
        (object_value, "is a class-field value"),
        (floor_value, "reflected source equality method is not constructed"),
        (comparison_op_sugar, "cannot be replaced by negated __eq__"),
    ):
        assert phrase not in inspect.getsource(module), (module, phrase)
