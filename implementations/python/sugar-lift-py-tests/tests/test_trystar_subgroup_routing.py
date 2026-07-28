"""TryStar subgroup routing — production laws.

ExceptionGroup testimony is partitioned by authenticated handler type through
``TryStarSugar`` + ``GroupedRaiseSugar`` only:

- matching subgroup reaches its handler (as-binding / bare re-raise / from)
- unmatched residual continues to subsequent handlers (source order)
- handler halt regroups with residual; finally restore / terminate override
- leaf occurrence identities and nested group topology survive partition
- ordinary ``Try`` never consumes grouped testimony
- type and occurrence lying twins refuse

Does not touch nodes.py, ExitSet/carrier algebra, assertion/resource routing,
or exception spelling rules. Acceptance is this file.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.effect_coordinate import ObservedEffectValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "trystar_subgroup.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return list(tree.functions())[-1].sugar().desugar()


def _leaves(effect) -> list[RaiseEffect]:
    out: list[RaiseEffect] = []

    def walk(node):
        if isinstance(node, RaiseEffect):
            out.append(node)
        elif isinstance(node, GroupedRaiseEffect):
            for child in node.children:
                walk(child)

    walk(effect)
    return out


def _halt_effect(outcome):
    """Project the single halt effect from Incomplete or a one-face ExitSet."""
    if isinstance(outcome, Incomplete):
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        return halted[0].effect
    raise AssertionError(f"expected Incomplete|ExitSet halt, got {type(outcome)}")


def _grouped_halt(outcome) -> GroupedRaiseEffect:
    effect = _halt_effect(outcome)
    assert isinstance(effect, GroupedRaiseEffect), type(effect)
    return effect


# ---------------------------------------------------------------------------
# Partition: authenticated type, residual continues, topology preserved
# ---------------------------------------------------------------------------


def test_partition_by_authenticated_type_keeps_unmatched_residual():
    """except* ValueError extracts VE leaves; TypeError residual continues."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError:\n"
            "        pass\n",
            name="part_residual.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["TypeError"], names


def test_nested_group_topology_survives_partial_partition():
    """Inner ExceptionGroup remains nested after a leaf is extracted."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'outer',\n"
            "            [TypeError(), ExceptionGroup('inner', [ValueError(), KeyError()])],\n"
            "        )\n"
            "    except* ValueError:\n"
            "        pass\n",
            name="nested_topology.py",
        )
    )
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "TypeError"
    nested = effect.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in nested.children] == ["KeyError"]


def test_all_matching_leaves_of_same_type_are_extracted():
    """except* never selects only the first leaf of a repeated type."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'g', [TypeError(), ValueError('a'), ValueError('b')]\n"
            "        )\n"
            "    except* ValueError:\n"
            "        pass\n",
            name="all_leaves.py",
        )
    )
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["TypeError"]


# ---------------------------------------------------------------------------
# Matching subgroup reaches handler; handlers in source order
# ---------------------------------------------------------------------------


def test_matched_subgroup_reaches_handler_as_binding():
    """``except* ValueError as e`` binds only the VE subgroup, not the residual."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError as e:\n"
            "        raise RuntimeError('from-handler') from e\n",
            name="matched_binding.py",
        )
    )
    primary = effect.children[0]
    assert isinstance(primary, RaiseEffect)
    assert primary.exception_name == "RuntimeError"
    assert isinstance(primary.cause_value, ObservedEffectValue)
    cause_leaves = _leaves(primary.cause_value.effect)
    assert [leaf.exception_name for leaf in cause_leaves] == ["ValueError"]
    residual = effect.children[1]
    assert isinstance(residual, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in _leaves(residual)] == ["TypeError"]


def test_handlers_run_in_source_order_not_group_leaf_order():
    """Second source handler runs after the first even if its type is earlier in the group."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'g', [ValueError(), TypeError(), KeyError()]\n"
            "        )\n"
            "    except* TypeError:\n"
            "        raise OSError('type-handler')\n"
            "    except* ValueError:\n"
            "        raise RuntimeError('value-handler')\n",
            name="source_order.py",
        )
    )
    # Source order: TypeError arm first, then ValueError arm, then residual KeyError.
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "OSError"
    assert isinstance(effect.children[1], RaiseEffect)
    assert effect.children[1].exception_name == "RuntimeError"
    residual = effect.children[2]
    assert isinstance(residual, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in _leaves(residual)] == ["KeyError"]


def test_subsequent_handler_consumes_prior_residual():
    """Unmatched remainder after first arm is available to the next arm."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    except* TypeError:\n"
        "        pass\n",
        name="subsequent.py",
    )
    assert isinstance(outcome, Complete), outcome


def test_type_tuple_handler_runs_body_once_for_all_listed_types():
    """``except* (A, B)`` is one handler: one body run over the union subgroup."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'g', [ValueError(), TypeError(), KeyError()]\n"
            "        )\n"
            "    except* (ValueError, TypeError):\n"
            "        raise RuntimeError('once')\n",
            name="type_tuple_once.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    # One RuntimeError (not two) + unmatched KeyError.
    assert names == ["RuntimeError", "KeyError"], names


# ---------------------------------------------------------------------------
# Handler halt regroup; finally restore / terminate override
# ---------------------------------------------------------------------------


def test_handler_halt_regroups_with_unmatched_residual():
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        raise KeyError('from-handler')\n",
            name="handler_halt.py",
        )
    )
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "KeyError"
    assert isinstance(effect.children[1], GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in _leaves(effect.children[1])] == [
        "TypeError"
    ]


def test_bare_reraise_regroups_matched_subgroup_with_residual():
    """Bare raise reconstructs original leaf set (matched + residual), no flatten."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        raise\n",
            name="bare_reraise.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["ValueError", "TypeError"], names


def test_finally_restore_preserves_residual_group():
    """Inert finally restores: residual TypeError still propagates."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        pass\n"
            "    finally:\n"
            "        x = 1\n",
            name="finally_restore.py",
        )
    )
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["TypeError"]


def test_finally_raise_overrides_residual_group():
    """Terminal finally raise supersedes residual ExceptionGroup."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        raise RuntimeError('finally-wins')\n",
        name="finally_raise.py",
    )
    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "RuntimeError"


def test_finally_return_overrides_residual_group():
    """Terminal finally return supersedes residual ExceptionGroup."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        return 99\n",
        name="finally_return.py",
    )
    assert isinstance(outcome, Complete), outcome
    record = outcome.value.record
    returns = [s for s in record.statements if isinstance(s, ReturnValue)]
    assert returns, record.statements
    assert returns[0].value.value == 99


# ---------------------------------------------------------------------------
# Occurrence identity survival; type / occurrence lying twins
# ---------------------------------------------------------------------------


def test_leaf_occurrence_identities_survive_partition_and_reraise():
    """Two same-type leaves keep distinct occurrences through bare re-raise."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'g', [ValueError('a'), ValueError('b'), TypeError()]\n"
            "        )\n"
            "    except* ValueError:\n"
            "        raise\n",
            name="occurrence_survive.py",
        )
    )
    leaves = _leaves(effect)
    value_errors = [leaf for leaf in leaves if leaf.exception_name == "ValueError"]
    type_errors = [leaf for leaf in leaves if leaf.exception_name == "TypeError"]
    assert len(value_errors) == 2
    assert len(type_errors) == 1
    assert value_errors[0].occurrence is not None
    assert value_errors[1].occurrence is not None
    assert value_errors[0].occurrence != value_errors[1].occurrence
    assert type_errors[0].occurrence is not None
    assert type_errors[0].occurrence != value_errors[0].occurrence


def test_renamed_subclass_matches_by_mro_identity():
    """Subclass constructed in source matches except* base via authenticated MRO."""
    effect = _grouped_halt(
        _desugar(
            "class Renamed(ValueError):\n"
            "    pass\n"
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [Renamed(), TypeError()])\n"
            "    except* ValueError:\n"
            "        pass\n",
            name="renamed_mro.py",
        )
    )
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["TypeError"]


def test_type_lying_twin_wrong_handler_type_does_not_match():
    """except* OSError must not absorb a ValueError leaf (spelling-adjacent twin)."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError('a')])\n"
            "    except* OSError:\n"
            "        raise RuntimeError('must-not-run')\n",
            name="type_lie.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["ValueError"], names
    assert "RuntimeError" not in names


def test_occurrence_lying_twin_matched_binding_is_not_residual_leaf():
    """Handler cause observation is the matched subgroup, never a residual sibling."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError('ve'), TypeError('te')])\n"
            "    except* ValueError as e:\n"
            "        raise RuntimeError('outer') from e\n",
            name="occ_lie.py",
        )
    )
    primary = effect.children[0]
    assert isinstance(primary.cause_value, ObservedEffectValue)
    cause_leaves = _leaves(primary.cause_value.effect)
    assert len(cause_leaves) == 1
    assert cause_leaves[0].exception_name == "ValueError"
    residual_leaves = _leaves(effect.children[1])
    assert [leaf.exception_name for leaf in residual_leaves] == ["TypeError"]
    # Distinct occurrences: cause leaf is not the residual TypeError occurrence.
    assert cause_leaves[0].occurrence != residual_leaves[0].occurrence


# ---------------------------------------------------------------------------
# Ordinary Try / TryStar membrane
# ---------------------------------------------------------------------------


def test_ordinary_try_cannot_consume_grouped_testimony():
    """Ordinary except ValueError leaves ExceptionGroup intact (not rewritten)."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except ValueError:\n"
            "        pass\n",
            name="ordinary_try.py",
        )
    )
    assert isinstance(effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["ValueError"]


def test_ordinary_try_except_exceptiongroup_still_does_not_split():
    """Even except ExceptionGroup on ordinary Try does not enter TryStar partition."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except ExceptionGroup:\n"
            "        pass\n",
            name="ordinary_eg.py",
        )
    )
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["ValueError"]


def test_trystar_refuses_ordinary_raise_effect():
    """except* over a non-group RaiseEffect stays loud (distinct routers)."""
    with pytest.raises(SugarNotWritten) as excinfo:
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('alone')\n"
            "    except* ValueError:\n"
            "        pass\n",
            name="star_on_ordinary.py",
        )
    assert "TryStarSugar" in str(excinfo.value)
    assert "GroupedRaiseEffect" in str(excinfo.value)


# ---------------------------------------------------------------------------
# GroupedRaiseSugar construction (nested, non-flattening)
# ---------------------------------------------------------------------------


def test_grouped_raise_constructs_nested_tree_without_flattening():
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    raise ExceptionGroup(\n"
            "        'outer',\n"
            "        [ValueError(), ExceptionGroup('inner', [TypeError(), KeyError()])],\n"
            "    )\n",
            name="construct_nested.py",
        )
    )
    assert len(effect.children) == 2
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "ValueError"
    nested = effect.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in nested.children] == [
        "TypeError",
        "KeyError",
    ]
    assert nested.children[0].occurrence != nested.children[1].occurrence
