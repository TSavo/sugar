"""Twins: a live loop run as its recurrence reads a name it carries through
its header alone as the recurrence's value, never refused by name.

```
def keys():
    return ({"a": 1}, {"b": 2})

TABLE = {}
for d in keys():
    TABLE.update(d)
```

A loop whose iterable's members the reduction does not hold (a call's
result, a formal) runs as its recurrence: one symbolic item, each name it
writes the fixed point of the loop's step (``LoopRecurrenceSugar._recurrence``).
The item reads a carried name through its header.  A name carried under a
binding coordinate had its header bound to the recurrence's value; a name
carried through its header alone -- a module binding, a name first bound in
the loop, a ``nonlocal`` cell -- had none (``_recurrence_starts``), so its
header was left unbound in the item and the read of ``TABLE`` in
``TABLE.update(d)`` was refused by name (``EvaluationRefSugar``: "read of
`TABLE` with its evaluation ...@loop:...#item unbound"), the module run with
it, and every function reading the global after it.  The first nine-step
lane run listed 19 pandas refusals of this shape from two module loops
(``core/computation/ops.py``: ``for d in (...): _binary_ops_dict.update(d)``;
``core/ops/docstrings.py``: ``for key in _op_names: _op_descriptions[...] =
...``) and nine more in function-level live loops.

Such a name is published through its post-loop key, and the recurrence
already states its value there (``recurrence_head`` of that key).  The item
now begins with that value (``_recurrence_starts``): what the earlier items
handed on, which nothing decides, so a read of it owes the undecided member
(``read_of_bound_value``) -- never the value before the loop, never a value
the solver picks.

Shapes:

- ``module-dict-update``: a module dict a module loop updates in place.
- ``module-subscript-store``: a module dict a module loop stores into,
  reading it in the same item.
- ``nonlocal-accumulator``: a ``nonlocal`` cell a live loop rebinds.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then real
``sugar prove``.  Neither half's lift refuses by ``EvaluationRefSugar``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source before the test, truthful claim, lying claim)``.
_SHAPES = {
    "module-dict-update": (
        "def parts():\n"
        "    return ({'a': 1}, {'b': 2})\n"
        "\n"
        "\n"
        "TABLE = {}\n"
        "for d in parts():\n"
        "    TABLE.update(d)\n",
        "len(TABLE) == 2",
        "len(TABLE) == 3",
    ),
    "module-subscript-store": (
        "def names():\n"
        "    return ['a']\n"
        "\n"
        "\n"
        "TABLE = {'a': 1}\n"
        "for key in names():\n"
        "    TABLE[key + '_r'] = TABLE[key]\n",
        "TABLE['a_r'] == 1",
        "TABLE['a_r'] == 2",
    ),
    "nonlocal-accumulator": (
        "def f(xs):\n"
        "    n = 0\n"
        "\n"
        "    def bump():\n"
        "        nonlocal n\n"
        "        for x in xs:\n"
        "            n += x\n"
        "\n"
        "    bump()\n"
        "    return n\n",
        "f([]) == 0",
        "f([]) == 1",
    ),
}


def _source(prefix: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after everything the shape runs before it)."""
    prefix = prefix + "\n\n"
    return (
        prefix + "def test_f():\n" + f"    assert {claim}\n",
        prefix.count("\n") + 1,
    )


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_recurrence_item_reads_a_header_carried_name_as_its_value(
    tmp_path: Path, shape: str, half: str
) -> None:
    prefix, truthful, lying = _SHAPES[shape]
    source, test_line = _source(prefix, truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # The loop's item reads the carried name: nothing is refused by name.
    assert "EvaluationRefSugar" not in json.dumps(result.lift_doc), result.lift_doc
    verdict = claim_verdict(
        result.prove_doc, claims_from_line=test_line, lift_doc=result.lift_doc
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
