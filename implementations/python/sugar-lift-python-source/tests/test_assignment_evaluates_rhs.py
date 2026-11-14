"""An assignment statement evaluates its RHS there, once, in statement order.

Substitution inlined ``x = <rhs>`` into every later read of ``x`` and left
the statement inert, so the RHS ran where ``x`` was READ:

- ``try: x = textwrap.dedent('a') except ValueError: x = 'h'; return x`` raised
  the call's exception at ``return x``, outside the ``try``, and the handler
  was unreachable;
- ``x = textwrap.dedent('a'); return 3`` and ``b = 1 // 0; return 3`` dropped
  the raise because ``x``/``b`` were never read.

Now the statement evaluates its RHS: its halts leave at the assignment, inside
whatever encloses it, and only its completed faces continue. A later read sees
the completed face's value and never re-evaluates (so a raise is counted
once). A tuple display evaluates every member left to right before any target
is assigned; a store target evaluates only its own target object after that.

The faces are read propositionally: each atom is an opaque boolean, and a row
(return or halt) is reachable under an assignment when its face guard and its
entry guards hold.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import _Atomic, _Connective, and_
from sugar_lift_py_tests.outcome import Halted

from test_undetermined_raise_except_matching import _exits

DEDENT = "UnprojectedSourceCall:textwrap.dedent"


def _rows(exits):
    """``(kind, payload, guard)`` for every return and halt the function leaves by."""
    rows = []
    for face in exits.exits:
        if isinstance(face, Halted):
            rows.append(("halt", face.effect, face.guard))
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()):
            name = type(entry).__name__
            if name == "GuardedReturn":
                rows.append(("return", entry.value, and_([face.guard, *entry.guards])))
            elif name == "ReturnValue":
                rows.append(("return", entry.value, face.guard))
            elif name == "Incomplete":
                rows.append(
                    ("halt", entry.effect, and_([face.guard, *entry.branch_conditions]))
                )
    return rows


def _atoms(formula, out):
    if isinstance(formula, _Atomic):
        out.setdefault(formula, None)
    elif isinstance(formula, _Connective):
        for operand in formula.operands:
            _atoms(operand, out)
    return out


def _holds(formula, env):
    if isinstance(formula, _Atomic):
        return env[formula]
    values = [_holds(operand, env) for operand in formula.operands]
    if formula.kind == "and":
        return all(values)
    if formula.kind == "or":
        return any(values)
    if formula.kind == "not":
        return not values[0]
    raise AssertionError(formula.kind)


def _label(kind, payload):
    if kind == "return":
        target = getattr(payload, "target_name", None)
        if target is not None:
            return f"return call:{target}"
        return "return " + repr(getattr(payload, "value", payload))
    if isinstance(payload, UndeterminedRaiseEffect):
        return f"halt {payload.producer_node_owner}@{_start(payload.occurrence)}"
    return "halt " + str(getattr(payload, "exception_name", type(payload).__name__))


_STARTS: dict[str, int] = {}


def _index_starts(source):
    """Each node's site coordinate CID -> its start offset in ``source``.

    An occurrence names its site by coordinate CID, never by a fragment's
    repr (#7808), so source order is read back through the source itself.
    """
    from sugar_lift_py_tests.occurrence import site_coordinate_cid
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile((source, "m.py", blake3_512_of(source.encode("utf-8"))))
    _STARTS.clear()
    for node in tree.nodes():
        fragment = getattr(node, "fragment", None)
        if fragment is not None:
            _STARTS.setdefault(site_coordinate_cid(fragment), fragment.span.start)


def _worlds(source, tmp_path):
    """Every atom assignment -> the sorted labels of the rows reachable there."""
    _index_starts(source)
    rows = _rows(_exits(tmp_path, source))
    atoms = {}
    for _kind, _payload, guard in rows:
        _atoms(guard, atoms)
    atoms = list(atoms)
    worlds = []
    for bits in itertools.product((False, True), repeat=len(atoms)):
        env = dict(zip(atoms, bits))
        worlds.append(
            (
                env,
                sorted(
                    _label(kind, payload)
                    for kind, payload, guard in rows
                    if _holds(guard, env)
                ),
            )
        )
    return atoms, worlds


def _start(site_text):
    """The start offset of the site an occurrence key names (its coordinate
    CID, before any ``@`` occurrence path)."""
    return _STARTS[str(site_text).split("@", 1)[0]]


def _call_start(atom):
    (call,) = atom.args
    return _start(call.args[-1].value)


def _completes(atom):
    return atom.name in ("python:source_call.completes",)


def _is_type(atom, name):
    return atom.name == "adt.is_python_type" and f"value='{name}'" in repr(atom)


def _every_world_takes_exactly_one_row(worlds):
    for _env, labels in worlds:
        assert len(labels) <= 1, labels


def test_a_try_around_the_assignment_routes_its_raise(tmp_path):
    source = (
        "import textwrap\n"
        "def f():\n"
        "    try:\n"
        "        x = textwrap.dedent('a')\n"
        "    except ValueError:\n"
        "        x = 'h'\n"
        "    return x\n"
    )
    atoms, worlds = _worlds(source, tmp_path)
    _every_world_takes_exactly_one_row(worlds)
    (completes,) = [atom for atom in atoms if _completes(atom)]
    (value_error,) = [atom for atom in atoms if _is_type(atom, "ValueError")]
    seen = set()
    for env, labels in worlds:
        if env[completes]:
            assert labels == ["return call:textwrap.dedent"]
        elif env[value_error]:
            # The handler ran: Python never reaches `return x` with the raise.
            assert labels == ["return 'h'"]
        else:
            assert len(labels) == 1 and labels[0].startswith("halt " + DEDENT)
        seen.add(tuple(labels))
    assert len(seen) == 3


@pytest.mark.parametrize(
    "statement",
    ("x = textwrap.dedent('a')", "a, b = textwrap.dedent('a'), 2", "x = y = textwrap.dedent('a')"),
    ids=("name", "display-unpack", "chained"),
)
def test_an_unread_assignment_still_raises(tmp_path, statement):
    source = f"import textwrap\ndef f():\n    {statement}\n    return 3\n"
    atoms, worlds = _worlds(source, tmp_path)
    _every_world_takes_exactly_one_row(worlds)
    (completes,) = [atom for atom in atoms if _completes(atom)]
    for env, labels in worlds:
        if env[completes]:
            assert labels == ["return 3"]
        else:
            assert len(labels) == 1 and labels[0].startswith("halt " + DEDENT)


@pytest.mark.parametrize(
    "read",
    ("return x", "return (x, x)", "y = x\n    return y"),
    ids=("once", "twice", "through-a-copy"),
)
def test_a_read_sees_the_completed_value_and_never_raises_again(tmp_path, read):
    source = f"import textwrap\ndef f():\n    x = textwrap.dedent('a')\n    {read}\n"
    rows = _rows(_exits(tmp_path, source))
    halts = [row for row in rows if row[0] == "halt"]
    # One occurrence, one raise: the read is the completed face's value.
    assert len(halts) == 1
    assert isinstance(halts[0][1], UndeterminedRaiseEffect)
    assert halts[0][1].producer_node_owner == DEDENT
    returns = [row for row in rows if row[0] == "return"]
    assert len(returns) == 1
    assert "textwrap.dedent" in repr(returns[0][1])


@pytest.mark.parametrize(
    "prefix",
    ("", "    x = 0\n"),
    ids=("literal", "substituted"),
)
def test_a_ground_division_by_zero_halts_at_the_assignment(tmp_path, prefix):
    divisor = "x" if prefix else "0"
    source = f"def f():\n{prefix}    b = 1 // {divisor}\n    return 3\n"
    rows = _rows(_exits(tmp_path, source))
    assert len(rows) == 1
    kind, effect, _guard = rows[0]
    assert kind == "halt"
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_name == "ZeroDivisionError"


def test_a_try_catches_the_assignment_division(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        b = 1 // 0\n"
        "    except ZeroDivisionError:\n"
        "        return 5\n"
        "    return 3\n"
    )
    rows = _rows(_exits(tmp_path, source))
    assert [(kind, repr(payload)) for kind, payload, _ in rows] == [
        ("return", "TermValue(value=5)")
    ]


def test_a_formal_division_is_the_same_carrier_as_its_expression_statement(tmp_path):
    """``b = 1 // x`` over a formal awaits caller actuals, exactly like ``1 // x``."""
    messages = []
    for statement in ("b = 1 // x", "1 // x"):
        root = tmp_path / str(len(messages))
        root.mkdir()
        with pytest.raises(ConstructionPanic) as caught:
            _exits(root, f"def f(x):\n    {statement}\n    return 3\n")
        assert "undischarged native operation demand" in str(caught.value)
        messages.append(str(caught.value).split("blame=")[0])
    assert messages[0] == messages[1]


def test_a_display_unpack_evaluates_every_member_before_any_target(tmp_path):
    source = (
        "import textwrap\n"
        "class O: pass\n"
        "def f():\n"
        "    o = O()\n"
        "    o.a, y = textwrap.dedent('p'), textwrap.dedent('q')\n"
        "    return y\n"
    )
    atoms, worlds = _worlds(source, tmp_path)
    _every_world_takes_exactly_one_row(worlds)
    completes = [atom for atom in atoms if _completes(atom)]
    assert len(completes) == 2
    # Source order: 'p' is the first member, so its call is evaluated first;
    # 'q' runs only where 'p' completed, and the store and bind only after both.
    first, second = sorted(completes, key=_call_start)
    for env, labels in worlds:
        if not env[first]:
            assert labels == [f"halt {DEDENT}@{_call_start(first)}"]
        elif not env[second]:
            assert labels == [f"halt {DEDENT}@{_call_start(second)}"]
        else:
            assert labels == ["return call:textwrap.dedent"]
