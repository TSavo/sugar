"""Twins: a module global an implicit dispatch may have changed is never read
as it was before that dispatch (#7757 H15).

#9108 made every explicit call bind a record of what it may have reached, so
a later call reads a mutable module global as that call left it
(``python:after(<call result>, "global:G")``).  An operation that is no
``Call`` node runs code too -- ``b[0]`` runs ``__getitem__``, ``b + 1``
``__add__``, ``with b:`` ``__enter__``, ``for _ in b:`` ``__iter__``,
``if b:`` ``__bool__``, ``b[0] = 5`` ``__setitem__``, ``-b`` ``__neg__`` --
and bound none, so a later call that read the global was handed it as the
caller's entry held it, and a lie could read ``sat``.

There is now one list of operations that may run code, the source tree's
(``container_mutation.may_run_code``), and one binder
(``call_site_value.bind_after_call``) every one of them takes, explicit call
or implicit dispatch: a face that ran code the lift did not read records
every module global.  An operation the floor answers by its own law (an item
of a list whose contents are current) records nothing.

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


def _shape(dunder: str, body: str, statement: str) -> str:
    """A module whose class ``B`` changes ``G`` in ``dunder`` (``body`` its
    return, indented under it), and whose ``f(b)`` runs ``statement`` on its
    formal before ``h()`` reads ``G``.  Braces are doubled: the source is a
    ``str.format`` template."""
    return (
        "G = [1]\n"
        "\n"
        "\n"
        "class B:\n"
        f"    def {dunder}:\n"
        "        G[0] = 2\n"
        f"        {body}\n"
        "\n"
        "\n"
        "def h():\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "def f(b):\n"
        f"{statement}"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n"
    )


# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    # An item read runs ``type(b).__getitem__``.
    "subscript": (
        _shape("__getitem__(self, i)", "return 0", "    b[0]\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # ``+`` runs ``type(b).__add__``.
    "binary-operator": (
        _shape("__add__(self, other)", "return 0", "    b + 1\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # A unary operator runs ``type(b).__neg__``.
    "unary-operator": (
        _shape("__neg__(self)", "return 0", "    -b\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # An item store runs ``type(b).__setitem__``.
    "item-store": (
        _shape("__setitem__(self, i, v)", "return None", "    b[0] = 5\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # ``with`` runs ``type(b).__enter__`` before its body.
    "with-enter": (
        _shape(
            "__enter__(self)",
            "return self\n"
            "\n"
            "    def __exit__(self, *exc):\n"
            "        return False",
            "    with b:\n        pass\n",
        ),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # ``for`` runs ``type(b).__iter__`` before its first item.
    "for-iter": (
        _shape("__iter__(self)", "return iter(())", "    for _ in b:\n        pass\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
    # ``if`` runs ``type(b).__bool__`` for its test.
    "if-truth": (
        _shape("__bool__(self)", "return False", "    if b:\n        pass\n"),
        "f(B()) == 2",
        "f(B()) == 1",
    ),
}

# The builtin shape: an item of a list whose contents are current runs no
# code, and records nothing; the global stands as the entry held it.
_SHAPES["builtin-item-runs-no-code"] = (
    "G = [1]\n"
    "\n"
    "\n"
    "def h():\n"
    "    return G[0]\n"
    "\n"
    "\n"
    "def f(n):\n"
    "    xs = [n]\n"
    "    xs[0]\n"
    "    n + 1\n"
    "    return h()\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert {claim}\n",
    "f(1) == 1",
    "f(1) == 2",
)


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_global_an_implicit_dispatch_may_change_is_never_read_as_before(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def test_the_one_list_of_operations_that_may_run_code() -> None:
    """``container_mutation.may_run_code`` -- the one list every record is
    bound by -- holds a call, an item read, an operator, a ``for``, a
    ``with`` and an ``if``; a name, a constant and an assignment are none."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.container_mutation import may_run_code
    from sugar_source_tree.tree import SourceFile

    source = (
        "def f(b, g):\n"
        "    x = b\n"
        "    y = b[0]\n"
        "    z = -b\n"
        "    w = b + 1\n"
        "    g()\n"
        "    for _ in b:\n"
        "        pass\n"
        "    with b:\n"
        "        pass\n"
        "    if b:\n"
        "        pass\n"
        "    return 1\n"
    )
    tree = SourceFile(
        (source, "may_run_code.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    found: dict = {}
    for node in tree.nodes():
        found.setdefault(node.kind, set()).add(may_run_code(node))
    for kind in ("Subscript", "UnaryOp", "BinOp", "Call", "For", "With", "If"):
        assert found.get(kind) == {True}, (kind, found)
    for kind in ("Name", "Constant", "Assign", "Return"):
        assert found.get(kind) == {False}, (kind, found)
