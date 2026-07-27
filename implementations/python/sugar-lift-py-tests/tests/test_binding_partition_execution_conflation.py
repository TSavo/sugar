"""The binding partition key is source-only, and nothing today reaches the hazard.

`branch_result_slot` keys a `binding.projection` partition on
``(source_cid, span, fragment_cid)`` -- **no execution component**
(`binding_state.py`). `_faces_exclusive` then proves two arms exclusive from
carried faces alone and never reads their guards, saying so in its own
docstring. So two arms from DIFFERENT executions that share a source-keyed
partition would be declared exclusive and collapsed.

This module states three things, and is careful about which is which:

1. **The collapse mechanism is real.** Proved directly against `partition` and
   `factor_completed` -- unrelated guards, one arm out, the second execution's
   value re-attributed to the negation of the first's guard.

2. **The key genuinely collides across executions.** Proved through the real
   substitution seam: specializing one source `if` with two different actuals
   yields the SAME slot id when the test is a compound expression.

3. **No source path reaches the hazard today** -- and the claim made here is
   "I could not find a path", NOT "no path exists". The tripwires below pin the
   three properties that currently stand between the mechanism and a real
   source, so that if any of them changes, this file goes red rather than the
   defect going live silently.

If a tripwire fails, do not adjust it. It means the conflation may now be
reachable, and the key needs an execution component before anything else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    _faces_exclusive,
    partition,
)


def _source(tmp_path: Path, name: str, text: str):
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return SourceFile(workspace_path_source(str(path), root=str(tmp_path)))


def _mint_count(monkeypatch, source_file) -> list[str]:
    """Every `binding.projection` slot minted while desugaring the file."""
    import sugar_lift_py_tests.sugar.guarded_binding_read_sugar as reader

    minted: list[str] = []
    original = reader._guarded_projection_faces

    def watched(state):
        minted.append(state.slot.slot_id)
        return original(state)

    monkeypatch.setattr(reader, "_guarded_projection_faces", watched)
    for function in source_file.functions():
        try:
            function.sugar().desugar(None)
        except BaseException:  # a refusal is not this module's subject
            pass
    return minted


# -- 1. the mechanism, proved rather than described ---------------------------


def test_two_executions_over_one_slot_collapse_into_one_arm() -> None:
    """THE HAZARD. Not a hypothetical: this is what would happen.

    `_faces_exclusive` reads faces only, so two arms whose guards are entirely
    unrelated are declared mutually exclusive because they carry opposite sides
    of a partition keyed on the SOURCE they came from.
    """
    slot = "branch-result:blake3-512:shared-by-two-executions"
    true_face, false_face = partition(("binding.projection", slot))
    first = atomic("execution_one_guard", [make_var("a")])
    second = atomic("execution_two_guard", [make_var("b")])

    assert _faces_exclusive(frozenset({true_face}), frozenset({false_face}))

    collapsed = ExitSet(
        (
            Completed(guard=first, value=TermValue(1), faces=frozenset({true_face})),
            Completed(guard=second, value=TermValue(2), faces=frozenset({false_face})),
        )
    ).factor_completed()

    # One arm, and the SECOND execution's value now rides on `not first`.
    assert len(collapsed.exits) == 1
    guarded = collapsed.exits[0].value
    assert guarded.guard == first
    assert guarded.when_true == TermValue(1)
    assert guarded.when_false == TermValue(2)


def test_faces_exclusive_never_consults_the_guards() -> None:
    """The discrimination: identical faces, wildly different guards, same answer."""
    true_face, false_face = partition(("binding.projection", "slot"))

    assert _faces_exclusive(frozenset({true_face}), frozenset({false_face}))
    # Same faces prove exclusivity regardless of what any guard says, because
    # no guard is passed to the predicate at all.
    assert not _faces_exclusive(frozenset({true_face}), frozenset({true_face}))


# -- 2. the key really does collide across executions -------------------------


def test_specializing_one_source_branch_twice_yields_ONE_slot(tmp_path) -> None:
    """The precondition, through the real substitution seam.

    A compound test keeps its own source fragment when its children are
    substituted, so two specializations of one function key on the same slot.
    """
    from sugar_source_tree.binding_state import branch_result_slot
    from sugar_source_tree.nodes import If, Name

    source_file = _source(
        tmp_path,
        "specialized.py",
        "def pick(c):\n"
        "    if c > 0:\n"
        "        x = 1\n"
        "    else:\n"
        "        x = 2\n"
        "    return x\n"
        "\n"
        "\n"
        "def caller(a, b):\n"
        "    return pick(a) + pick(b)\n",
    )
    pick = [f for f in source_file.functions() if f.name == "pick"][0]
    branch = [n for n in pick.walk() if isinstance(n, If)][0]

    slots = []
    for actual in ("a", "b"):
        argument = [
            n for n in source_file.root.walk() if isinstance(n, Name) and n.id == actual
        ][0]
        body, _changed = pick._substitute_body((branch,), {"c": argument})
        slots.append(branch_result_slot(body[0].test).slot_id)

    assert slots[0] == slots[1], "the key would not collide; hazard precondition gone"


def test_a_bare_name_test_does_NOT_collide(tmp_path) -> None:
    """The discriminating arm: substitution re-keys a bare test to the actual.

    `if c:` replaces the whole test node, so each specialization takes the
    ACTUAL's fragment and the slots differ. Only a compound test collides --
    a distinction a one-shape experiment would have missed.
    """
    from sugar_source_tree.binding_state import branch_result_slot
    from sugar_source_tree.nodes import If, Name

    source_file = _source(
        tmp_path,
        "bare.py",
        "def pick(c):\n"
        "    if c:\n"
        "        x = 1\n"
        "    else:\n"
        "        x = 2\n"
        "    return x\n"
        "\n"
        "\n"
        "def caller(a, b):\n"
        "    return pick(a) + pick(b)\n",
    )
    pick = [f for f in source_file.functions() if f.name == "pick"][0]
    branch = [n for n in pick.walk() if isinstance(n, If)][0]

    slots = []
    for actual in ("a", "b"):
        argument = [
            n for n in source_file.root.walk() if isinstance(n, Name) and n.id == actual
        ][0]
        body, _changed = pick._substitute_body((branch,), {"c": argument})
        slots.append(branch_result_slot(body[0].test).slot_id)

    assert slots[0] != slots[1]


# -- 3. tripwires: what currently stands between mechanism and source ---------


def test_tripwire_a_two_branch_binding_never_mints(tmp_path, monkeypatch) -> None:
    """`x` bound in BOTH branches becomes an IfExp, not a GuardedBinding.

    `binding_state.py` returns `make_ifexp(...)` when both sides are plain
    Nodes, so the partition is never minted. If this starts minting, the most
    common conditional-binding shape in real code gains a source-keyed
    partition and the hazard surface widens enormously.
    """
    source_file = _source(
        tmp_path,
        "two_branch.py",
        "def pick(c):\n"
        "    if c > 0:\n"
        "        x = 1\n"
        "    else:\n"
        "        x = 2\n"
        "    return x\n",
    )

    assert _mint_count(monkeypatch, source_file) == []


def test_tripwire_a_one_branch_binding_DOES_mint(tmp_path, monkeypatch) -> None:
    """The discrimination for the tripwire above: the mint is reachable at all.

    Without this, `_mint_count` returning [] everywhere would satisfy every
    tripwire in this file while measuring nothing.
    """
    source_file = _source(
        tmp_path,
        "one_branch.py",
        "def one_branch(c):\n    if c > 0:\n        x = 1\n    return x\n",
    )

    assert len(_mint_count(monkeypatch, source_file)) == 1


def test_tripwire_b_two_call_sites_do_not_specialize_the_callee(
    tmp_path, monkeypatch
) -> None:
    """Ordinary calls stay opaque, so one callee is not reduced twice.

    `pick(a) + pick(b)` desugars to `call:pick` terms. If calls begin
    specializing here, two executions of one source branch could meet in one
    ExitSet -- which is the missing half of the hazard.
    """
    source_file = _source(
        tmp_path,
        "two_calls.py",
        "def pick(c):\n"
        "    if c > 0:\n"
        "        x = 1\n"
        "    return x\n"
        "\n"
        "\n"
        "def caller(a, b):\n"
        "    return pick(a) + pick(b)\n",
    )

    minted = _mint_count(monkeypatch, source_file)

    # Exactly one: `pick`'s own reduction. Not one per call site.
    assert len(minted) == 1, minted
    assert len(set(minted)) == 1


def test_tripwire_c_a_loop_body_does_not_mint_this_partition(
    tmp_path, monkeypatch
) -> None:
    """A loop routes through the LOOP projection, not this one.

    A loop is the one shape that supplies many executions over one source
    location by construction. It currently mints `LoopGuardedProjection`
    instead, so it never reaches this partition. If that changes, the hazard
    becomes reachable without needing specialization at all.
    """
    source_file = _source(
        tmp_path,
        "loop_body.py",
        "def accumulate(items, c):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if c > 0:\n"
        "            x = 1\n"
        "        total = total + x\n"
        "    return total\n",
    )

    assert _mint_count(monkeypatch, source_file) == []


def test_tripwire_d_distinct_source_branches_keep_distinct_slots(
    tmp_path, monkeypatch
) -> None:
    """Two different `if`s must never share a slot -- the key's one real job."""
    source_file = _source(
        tmp_path,
        "two_ifs.py",
        "def sequential(c, d):\n"
        "    if c > 0:\n"
        "        x = 1\n"
        "    a = x\n"
        "    if d > 0:\n"
        "        y = 2\n"
        "    b = y\n"
        "    return a + b\n",
    )

    minted = _mint_count(monkeypatch, source_file)

    assert len(minted) == 2
    assert len(set(minted)) == 2, "two distinct source branches collided"
