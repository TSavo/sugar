"""A ``str`` method's result over an undecided argument is the one call
result, and a ``bytes`` literal answers ``in``, iteration and indexing as a
``str`` does (#7757 S8, H17; #7789's computed half).

Before, ``s.split(sep)``, ``s.strip(chars)``, ``s.splitlines(keepends)`` and
``sep.join(<undecided>)`` minted ``OpaqueOpCallsite``: a second call-result
class, its ``computed`` field ``None`` at its only constructor, so the
computed-sibling machinery was dead.  It hand-delegated each protocol to a
``SymbolicValue`` and missed ``in`` and iteration: ``x in s.split(sep)`` and
``for p in s.split(sep)`` were construction panics.  It also completed with
no halt, though ``"abc".strip(5)`` raises ``TypeError`` and ``"a".split("")``
raises ``ValueError``.

Now ``split``/``strip``/``splitlines`` over such an argument is the one
unanswered call (two faces, owed); ``join`` is the one call result
(``CallSiteValue``) after its iteration.  A ``bytes`` literal decides ``in``
and indexing where the operands are ground, as a ``str`` does.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_TEST = "def test_f():\n    assert {claim}\n"


def _raises(call: str, exception: str) -> str:
    """A test that records whether ``call`` raised ``exception``."""
    return (
        "def test_f():\n"
        "    try:\n"
        f"        {call}\n"
        "        ok = True\n"
        f"    except {exception}:\n"
        "        ok = False\n"
        "    assert {claim}\n"
    )


# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    "in-a-split-by-a-formal-separator": (
        "def f(sep):\n"
        '    return "a" in "a,b".split(sep)\n'
        "\n"
        "\n" + _TEST,
        'f(",") == True',
        'f(",") == False',
    ),
    "in-a-formals-split": (
        "def f(s, sep):\n"
        '    return "a" in s.split(sep)\n'
        "\n"
        "\n" + _TEST,
        'f("a,b", ",") == True',
        'f("a,b", ",") == False',
    ),
    "for-over-a-split-by-a-formal-separator": (
        "def f(sep):\n"
        "    out = []\n"
        '    for p in "a,b".split(sep):\n'
        "        out.append(p)\n"
        "    return out\n"
        "\n"
        "\n" + _TEST,
        'f(",") == ["a", "b"]',
        'f(",") == ["a,b"]',
    ),
    "comprehension-over-a-formals-split": (
        "def f(s, sep):\n"
        "    return [p for p in s.split(sep)]\n"
        "\n"
        "\n" + _TEST,
        'f("a,b", ",") == ["a", "b"]',
        'f("a,b", ",") == ["a,b"]',
    ),
    # The halts the coordinate dropped.
    "strip-by-a-non-str-raises": (
        "def f(chars):\n"
        '    return "abc".strip(chars)\n'
        "\n"
        "\n" + _raises("f(5)", "TypeError"),
        "not ok",
        "ok",
    ),
    "split-by-an-empty-separator-raises": (
        "def f(sep):\n"
        '    return "a,b".split(sep)\n'
        "\n"
        "\n" + _raises('f("")', "ValueError"),
        "not ok",
        "ok",
    ),
    "in-a-join-result": (
        "def f(xs):\n"
        '    return "a" in ",".join(xs)\n'
        "\n"
        "\n" + _TEST,
        'f(["a"]) == True',
        'f(["a"]) == False',
    ),
    # ``bytes``: decided where ground, as a ``str`` is.
    "bytes-in-bytes": (
        "def f():\n"
        '    return b"\\n" in b"a\\nb"\n'
        "\n"
        "\n" + _TEST,
        "f() == True",
        "f() == False",
    ),
    "int-in-bytes": (
        "def f():\n"
        '    return 98 in b"ab"\n'
        "\n"
        "\n" + _TEST,
        "f() == True",
        "f() == False",
    ),
    "int-out-of-range-in-bytes-raises": (
        "def f():\n"
        '    return 256 in b"ab"\n'
        "\n"
        "\n" + _raises("f()", "ValueError"),
        "not ok",
        "ok",
    ),
    "str-in-bytes-raises": (
        "def f():\n"
        '    return "a" in b"a"\n'
        "\n"
        "\n" + _raises("f()", "TypeError"),
        "not ok",
        "ok",
    ),
    "formal-in-bytes": (
        "def f(x):\n"
        '    return x in b"ab"\n'
        "\n"
        "\n" + _TEST,
        "f(97) == True",
        "f(97) == False",
    ),
    "bytes-index": (
        "def f():\n"
        '    return b"ab"[1]\n'
        "\n"
        "\n" + _TEST,
        "f() == 98",
        "f() == 97",
    ),
    "bytes-slice": (
        "def f():\n"
        '    return b"abc"[1:]\n'
        "\n"
        "\n" + _TEST,
        'f() == b"bc"',
        'f() == b"ab"',
    ),
    "for-over-bytes": (
        "def f():\n"
        "    out = []\n"
        '    for byte in b"ab":\n'
        "        out.append(byte)\n"
        "    return out\n"
        "\n"
        "\n" + _TEST,
        "f() == [97, 98]",
        "f() == [98, 97]",
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
def test_a_str_method_result_and_bytes_never_admit_a_lie_nor_refute_a_truth(
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
# Lift units
# ---------------------------------------------------------------------------


def _outcome(source: str, name: str = "f"):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "str_method.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


@pytest.mark.parametrize(
    "expression",
    [
        '"a,b".split(sep)',
        '"abc".strip(sep)',
        '"a\\nb".splitlines(sep)',
        '[p for p in "a,b".split(sep)]',
        '"a" in "a,b".split(sep)',
    ],
    ids=["split", "strip", "splitlines", "comprehension", "membership"],
)
def test_a_str_method_over_a_formal_is_the_unanswered_call_never_a_panic(
    expression: str,
) -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    outcome = _outcome(f"def f(sep):\n    return {expression}\n")
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert any(
        isinstance(face.effect, UndeterminedRaiseEffect) for face in halts
    ), outcome


def test_the_second_call_result_class_is_gone() -> None:
    spec = importlib.util.find_spec("sugar_lift_py_tests.floor.opaque_op_callsite")
    assert spec is None


# ---------------------------------------------------------------------------
# Bytes floor units
# ---------------------------------------------------------------------------


def _bool(outcome) -> bool:
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    value = outcome.completed_value()
    assert type(value) in (TrueBoolLiteralSugar, FalseBoolLiteralSugar), outcome
    return type(value) is TrueBoolLiteralSugar


def _raised(outcome) -> list:
    return [face.effect.exception_name for face in outcome.halts()]


def _fragment(source: str, kind: str):
    """The source fragment of the one ``kind`` node of ``source``: a ground
    exit cites source it can re-read (a filename and the unit holding its
    text, ``ground_exit.ground_raise_effect``), never a bare string."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile((source, "bytes_floor.py", blake3_512_of(source.encode())))
    (fragment,) = (node.fragment for node in tree.nodes() if node.kind == kind)
    return fragment


def test_bytes_membership_is_decided_where_ground() -> None:
    from sugar_lift_py_tests.floor import StringValue, TermValue
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    site = _fragment("x in b'a'\n", "Compare")
    haystack = BytesValue(b"a\nb")
    assert _bool(haystack.contains(BytesValue(b"\n"), site)) is True
    assert _bool(haystack.contains(BytesValue(b"z"), site)) is False
    assert _bool(haystack.contains(TermValue(98), site)) is True
    assert _bool(haystack.contains(TermValue(99), site)) is False
    assert _bool(BytesValue(b"\x01").contains(TrueBoolLiteralSugar(site="t"), site))
    assert _raised(haystack.contains(TermValue(256), site)) == ["ValueError"]
    assert _raised(haystack.contains(TermValue(-1), site)) == ["ValueError"]
    assert _raised(haystack.contains(StringValue("a"), site)) == ["TypeError"]
    assert _raised(haystack.contains(TermValue(1.5), site)) == ["TypeError"]


def test_bytes_membership_of_an_undecided_needle_is_the_undecided_form() -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.ir import make_var

    outcome = BytesValue(b"ab").contains(SymbolicValue(make_var("x")), "in")
    assert outcome.completed_value() is None
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert outcome.owed_items()


def test_bytes_index_is_decided_where_ground() -> None:
    from sugar_lift_py_tests.floor import StringValue, TermValue
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.slice_value import SliceValue

    site = _fragment("b'abc'[i]\n", "Subscript")
    value = BytesValue(b"abc")
    assert value.subscript(TermValue(1), site).completed_value() == TermValue(98)
    assert value.subscript(TermValue(-1), site).completed_value() == TermValue(99)
    assert _raised(value.subscript(TermValue(3), site)) == ["IndexError"]
    assert value.subscript(
        SliceValue(TermValue(1), None, None), site
    ).completed_value() == BytesValue(b"bc")
    assert _raised(value.subscript(SliceValue(None, None, TermValue(0)), site)) == [
        "ValueError"
    ]
    assert _raised(value.subscript(StringValue("a"), site)) == ["TypeError"]
