"""Twins: a source exception class with no ``__init__`` states its
constructor contract, ``args`` the ``*args`` formal itself (#7757 step 6).

A class whose constructor is ``BaseException``'s takes the inherited frame
``(*args)`` (``ClassDef.source_visible_constructor_frame``), and the
construction stores the call's positional actuals as ``args``
(``ClassConstructorBodySugar._carrying_exception_args``, as
``BaseException_new`` does).  It required a ``TupleValue`` at the formal.  A
call's binder binds one; the class's own contract
(``tree_enumerate.class_universe_outcome``) binds the formal standing free,
as every contract formal stands, so every such class refused its own
contract by name (``ClassConstructorBodySugar.exception_args``, observed
``SymbolicValue bound at the *args formal``): 37 classes of
``pandas/errors/__init__.py`` on the first nine-step lane (d5dcbab5c).

The free formal is now what ``args`` holds in the contract: exactly what the
call's edge supplies packed at prove.

A lying claim is never ``sat``; a truthful one is never ``unsat``; and the
class states its contract, not a refused member.  Each half goes through
``run_source_through_real_solver``: real ``sugar mint`` then real ``sugar
prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_TEST = "def test_f():\n    assert {claim}\n"

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    "docstring-only-exception": (
        "class Oops(ValueError):\n"
        '    """Raised when it goes wrong."""\n'
        "\n"
        "\n" + _TEST,
        'Oops("m").args == ("m",)',
        'Oops("m").args == ("n",)',
    ),
    "exception-of-a-source-exception": (
        "class Base(Exception):\n"
        "    pass\n"
        "\n"
        "\n"
        "class Oops(Base):\n"
        "    pass\n"
        "\n"
        "\n" + _TEST,
        'Oops("m", 2).args == ("m", 2)',
        'Oops("m", 2).args == ("m",)',
    ),
}


def _claims_line(source: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


def _refused_owners(lift_doc: dict) -> list:
    return [
        row["reason"]["refused"]["owner"]
        for row in lift_doc.get("ir", [])
        if row.get("kind") == "undecided" and "refused" in (row.get("reason") or {})
    ]


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_an_inherited_exception_constructor_states_its_contract(
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
    assert "ClassConstructorBodySugar.exception_args" not in _refused_owners(
        result.lift_doc
    ), result.lift_doc
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    if half == "lying":
        assert verdict != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
