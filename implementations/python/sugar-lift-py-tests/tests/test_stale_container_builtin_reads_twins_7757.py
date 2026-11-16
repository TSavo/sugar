"""Twins: a builtin never reads a container by contents that are not current
(#7757 H8, H9, L2).

``enumerate(xs)`` built a decided iterator of ``(index, member)`` pairs from
``xs``'s elements, and ``builtin_typed_value`` / ``_hashable_members`` read
``xs``'s elements to decide that ``str(xs)``, ``repr(xs)`` and ``set(xs)``
never raise -- with no ``contents_stale`` check.  A module global list that
another function changed arrives stale, so the lift iterated, displayed and
hashed the contents it arrived with: ``enumerate`` decided the old first
member, and ``str``/``repr``/``set`` completed with no halt face though the
list now holds a member whose ``__repr__`` raises or that is unhashable.

Now a container whose contents are not current is read by its identity:
``enumerate`` over it is the bodiless call that names it so
(``BuiltinSemanticCallable._unhandled_construct``), and it is not a decided
builtin "all the way down", so ``str``/``repr``/``set`` over it are the one
unanswered call, two-faced and owed.  ``builtin_call_total`` also states
its own operand condition for ``print``/``str``/``bool``/``repr``/``all``/
``any`` (L2), so no reader of it completes ``str(<formal>)``.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # ``bump`` changes the global's first member; ``enumerate`` over the
    # global read the member it arrived with (H8).
    "enumerate-over-a-global-another-function-changed": (
        "XS = [1, 2]\n"
        "\n"
        "\n"
        "def bump():\n"
        "    XS[0] = 9\n"
        "\n"
        "\n"
        "def test_first():\n"
        "    bump()\n"
        "    x = 0\n"
        "    for _, y in enumerate(XS):\n"
        "        x = y\n"
        "        break\n"
        "    assert {claim}\n",
        "x == 9",
        "x == 1",
    ),
    # The same read through a function's own contract.
    "enumerate-over-a-global-read-in-a-callee": (
        "XS = [1, 2]\n"
        "\n"
        "\n"
        "def bump():\n"
        "    XS[0] = 9\n"
        "\n"
        "\n"
        "def first():\n"
        "    for _, x in enumerate(XS):\n"
        "        return x\n"
        "    return 0\n"
        "\n"
        "\n"
        "def test_first():\n"
        "    bump()\n"
        "    assert {claim}\n",
        "first() == 9",
        "first() == 1",
    ),
    # ``str`` of the global runs ``Bad.__repr__`` once ``add`` put one in it
    # (H9): ``str`` completed outright from the old ``[1]``.
    "str-over-a-global-another-function-changed": (
        "class Bad:\n"
        "    def __repr__(self):\n"
        '        raise ValueError("no repr")\n'
        "\n"
        "\n"
        "XS = [1]\n"
        "\n"
        "\n"
        "def add():\n"
        "    XS.append(Bad())\n"
        "\n"
        "\n"
        "def test_s():\n"
        "    add()\n"
        "    try:\n"
        "        str(XS)\n"
        "        ok = True\n"
        "    except ValueError:\n"
        "        ok = False\n"
        "    assert {claim}\n",
        "not ok",
        "ok",
    ),
    # ``repr`` of a tuple holding the global: decided "all the way down"
    # read the list's old members.
    "repr-of-a-tuple-holding-a-changed-global": (
        "class Bad:\n"
        "    def __repr__(self):\n"
        '        raise ValueError("no repr")\n'
        "\n"
        "\n"
        "XS = [1]\n"
        "\n"
        "\n"
        "def add():\n"
        "    XS.append(Bad())\n"
        "\n"
        "\n"
        "def test_s():\n"
        "    add()\n"
        "    try:\n"
        "        repr((XS,))\n"
        "        ok = True\n"
        "    except ValueError:\n"
        "        ok = False\n"
        "    assert {claim}\n",
        "not ok",
        "ok",
    ),
    # ``set`` of the global hashes a list ``add`` put in it: ``TypeError``.
    # ``_hashable_members`` read the old ``[1]`` and completed it outright.
    "set-over-a-global-another-function-changed": (
        "XS = [1]\n"
        "\n"
        "\n"
        "def add():\n"
        "    XS.append([])\n"
        "\n"
        "\n"
        "def test_s():\n"
        "    add()\n"
        "    try:\n"
        "        set(XS)\n"
        "        ok = True\n"
        "    except TypeError:\n"
        "        ok = False\n"
        "    assert {claim}\n",
        "not ok",
        "ok",
    ),
    # An f-string over the global formats it through ``Bad.__repr__``; its
    # term names the list by its identity, never its old contents.
    "fstring-over-a-global-another-function-changed": (
        "class Bad:\n"
        "    def __repr__(self):\n"
        '        raise ValueError("no repr")\n'
        "\n"
        "\n"
        "XS = [1]\n"
        "\n"
        "\n"
        "def add():\n"
        "    XS.append(Bad())\n"
        "\n"
        "\n"
        "def test_s():\n"
        "    add()\n"
        "    try:\n"
        '        f"{{XS}}"\n'
        "        ok = True\n"
        "    except ValueError:\n"
        "        ok = False\n"
        "    assert {claim}\n",
        "not ok",
        "ok",
    ),
    # A list this frame made and nothing changed keeps its decided pairs.
    "enumerate-over-a-current-list-keeps-its-pairs": (
        "def test_first():\n"
        "    xs = [1, 2]\n"
        "    x = 0\n"
        "    for _, y in enumerate(xs):\n"
        "        x = y\n"
        "        break\n"
        "    assert {claim}\n",
        "x == 1",
        "x == 2",
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
def test_a_builtin_never_reads_stale_contents(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def _stale_and_current():
    from sugar_lift_py_tests.floor import ListValue, TermValue

    one = TermValue(1)
    stale = ListValue((one,), allocation=None, arrival="read")
    current = ListValue((one,), allocation="made")
    return stale, current


def test_a_stale_container_is_not_decided_all_the_way_down() -> None:
    """``builtin_typed_value`` reads members only of a current container;
    its shallow form reads only the type, which a stale list keeps."""
    from sugar_lift_py_tests.floor import TupleValue
    from sugar_lift_py_tests.source_call_resolution import builtin_typed_value

    stale, current = _stale_and_current()
    assert not builtin_typed_value(stale)
    assert not builtin_typed_value(TupleValue((stale,)))
    assert builtin_typed_value(stale, shallow=True)
    assert builtin_typed_value(current)


def test_set_of_a_stale_list_is_not_total() -> None:
    from sugar_source_tree.nodes import LanguageCallee

    from sugar_lift_py_tests.source_call_resolution import builtin_call_total

    stale, current = _stale_and_current()
    assert not builtin_call_total(LanguageCallee.BUILTIN_SET, (stale,))
    assert builtin_call_total(LanguageCallee.BUILTIN_SET, (current,))


def test_str_repr_bool_print_all_any_state_their_own_operand_condition() -> None:
    """L2: ``builtin_call_total`` never lists these "over any operand", so
    ``call_site_sugar._builtin_law_answers`` -- which asks it with no
    filter of its own -- never completes ``str(<formal>)``."""
    from sugar_source_tree.nodes import LanguageCallee as L

    from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.source_call_resolution import builtin_call_total

    formal = SymbolicValue(make_var("x"))
    stale, _ = _stale_and_current()
    for callee in (L.BUILTIN_STR, L.BUILTIN_REPR, L.BUILTIN_BOOL, L.BUILTIN_PRINT):
        assert not builtin_call_total(callee, (formal,)), callee
        assert not builtin_call_total(callee, (stale,)), callee
        assert builtin_call_total(callee, (TermValue(1),)), callee
    for callee in (L.BUILTIN_ALL, L.BUILTIN_ANY):
        assert not builtin_call_total(
            callee, (ListValue((formal,), allocation="made"),)
        ), callee
        assert builtin_call_total(
            callee, (ListValue((TermValue(1),), allocation="made"),)
        ), callee


def _site(tmp_path: Path):
    """The fragment of ``return enumerate(XS)`` in ``f``."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "stale_enumerate.py"
    path.write_text("XS = [1]\n\n\ndef f():\n    return enumerate(XS)\n")
    tree = open_source_file_for_construction(path, root=tmp_path)
    function = next(tree.functions())
    return function.body[0].fragment


def test_enumerate_of_a_stale_list_names_it_by_identity(tmp_path: Path) -> None:
    """H8: no iterator of the old pairs; the bodiless ``enumerate`` call,
    its operand ``python:object_read(...)``."""
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import CallSiteValue, ListIteratorValue
    from sugar_lift_py_tests.floor.builtin_semantic_callable import (
        BuiltinSemanticCallable,
    )
    from sugar_lift_py_tests.outcome import Completed

    site = _site(tmp_path)
    stale, _ = _stale_and_current()
    builtin = BuiltinSemanticCallable(operation="python.enumerate.construct")

    outcome = builtin.callable_application_with(
        CallableApplication((stale,), (), site), None
    )

    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert completed, outcome
    for arm in completed:
        assert not isinstance(arm.value, ListIteratorValue), arm
        assert isinstance(arm.value, CallSiteValue), arm
        (operand,) = arm.value.term.args
        assert operand.name == "python:object_read", operand
