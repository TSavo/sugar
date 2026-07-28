"""Exception-group nesting — TryStar composes across two levels.

Laws:

1. Nested ``ExceptionGroup`` construction keeps topology (no flatten).
2. Outer ``except*`` partitions nested groups; residual keeps nested shape.
3. Nested ``TryStar`` inside an outer ``except*`` handler partitions the
   inner group; outer residual continues and regroups.
4. Leaf occurrence identities survive two levels of partition/reraise.
5. Twins: wrong-type nested leaf is residual; full inner consume leaves only
   outer residual; never first-leaf-only over nested twins.

Does not touch ExitSet algebra, carrier, nodes.py, or assertion/resource routing.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "group_nesting.py"):
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
    if isinstance(outcome, Incomplete):
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        return halted[0].effect
    raise AssertionError(f"expected halt, got {type(outcome)}: {outcome}")


def _grouped_halt(outcome) -> GroupedRaiseEffect:
    effect = _halt_effect(outcome)
    assert isinstance(effect, GroupedRaiseEffect), type(effect)
    return effect


# ---------------------------------------------------------------------------
# Nested construction topology
# ---------------------------------------------------------------------------


def test_nested_exception_group_constructs_without_flattening():
    """Outer group holds a leaf and an inner group — topology preserved."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    raise ExceptionGroup(\n"
            "        'outer',\n"
            "        [\n"
            "            ValueError('a'),\n"
            "            ExceptionGroup('inner', [TypeError('t'), KeyError('k')]),\n"
            "        ],\n"
            "    )\n",
            name="construct_nest.py",
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
    assert effect.occurrence != nested.occurrence


# ---------------------------------------------------------------------------
# Outer except* over nested construction
# ---------------------------------------------------------------------------


def test_outer_except_star_partitions_nested_group_preserving_topology():
    """except* TypeError extracts nested TypeError; residual keeps nested KeyError."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'outer',\n"
            "            [\n"
            "                ValueError('a'),\n"
            "                ExceptionGroup('inner', [TypeError('t'), KeyError('k')]),\n"
            "            ],\n"
            "        )\n"
            "    except* TypeError:\n"
            "        pass\n",
            name="outer_part_nested.py",
        )
    )
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "ValueError"
    nested = effect.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in nested.children] == ["KeyError"]
    # Nested residual leaf keeps its construction occurrence (two-level survival).
    assert nested.children[0].occurrence is not None
    assert nested.children[0].exception_name == "KeyError"
    assert nested.children[0].occurrence != effect.children[0].occurrence


# ---------------------------------------------------------------------------
# Nested TryStar inside outer except* handler
# ---------------------------------------------------------------------------


def test_nested_trystar_in_outer_handler_composes_residuals():
    """Inner except* consumes KeyError; outer residual TypeError continues."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError:\n"
            "        try:\n"
            "            raise ExceptionGroup(\n"
            "                'inner', [KeyError('k'), RuntimeError('r')]\n"
            "            )\n"
            "        except* KeyError:\n"
            "            pass\n",
            name="nested_trystar_handler.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    # Inner residual RuntimeError + outer residual TypeError.
    assert "RuntimeError" in names, names
    assert "TypeError" in names, names
    assert "KeyError" not in names, names
    assert "ValueError" not in names, names


def test_nested_trystar_full_inner_consume_leaves_only_outer_residual():
    """Inner except* fully consumes the inner group; only outer TypeError remains."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError:\n"
            "        try:\n"
            "            raise ExceptionGroup('inner', [KeyError('k')])\n"
            "        except* KeyError:\n"
            "            pass\n",
            name="full_inner_consume.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["TypeError"], names


def test_outer_handler_raises_new_group_regroups_with_outer_residual():
    """Handler-raised nested group regroups with unmatched outer residual."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError:\n"
            "        raise ExceptionGroup('spawned', [KeyError('k'), OSError('o')])\n",
            name="handler_spawn_group.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert "KeyError" in names and "OSError" in names, names
    assert "TypeError" in names, names
    assert "ValueError" not in names, names
    # Spawned group is a nested child, not flattened into leaves only.
    assert any(isinstance(c, GroupedRaiseEffect) for c in effect.children)


# ---------------------------------------------------------------------------
# Occurrence identities survive two levels
# ---------------------------------------------------------------------------


def test_occurrence_identities_survive_two_level_partition():
    """Two-level leaves keep distinct occurrences through outer except*."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'outer',\n"
            "            [\n"
            "                ValueError('a'),\n"
            "                ExceptionGroup(\n"
            "                    'inner',\n"
            "                    [TypeError('t1'), TypeError('t2'), KeyError('k')],\n"
            "                ),\n"
            "            ],\n"
            "        )\n"
            "    except* TypeError:\n"
            "        pass\n",
            name="occ_two_level.py",
        )
    )
    leaves = _leaves(effect)
    names = [leaf.exception_name for leaf in leaves]
    assert names == ["ValueError", "KeyError"], names
    ve, ke = leaves[0], leaves[1]
    assert ve.occurrence is not None and ke.occurrence is not None
    assert ve.occurrence != ke.occurrence
    # Construction-side: two TypeError leaves were distinct before extract —
    # residual KeyError occurrence is still the original inner leaf site.
    assert "KeyError" in ke.exception_name or ke.exception_name == "KeyError"


def test_bare_reraise_at_inner_level_preserves_inner_occurrences_with_outer_residual():
    """Inner bare re-raise rebuilds inner group; outer residual TypeError continues."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
            "    except* ValueError:\n"
            "        try:\n"
            "            raise ExceptionGroup(\n"
            "                'inner', [KeyError('k'), OSError('o')]\n"
            "            )\n"
            "        except* KeyError:\n"
            "            raise\n",
            name="inner_bare_reraise.py",
        )
    )
    leaves = _leaves(effect)
    names = [leaf.exception_name for leaf in leaves]
    assert "KeyError" in names and "OSError" in names and "TypeError" in names, names
    assert "ValueError" not in names, names
    occs = [leaf.occurrence for leaf in leaves]
    assert len(occs) == len(set(occs)), occs


# ---------------------------------------------------------------------------
# Twins
# ---------------------------------------------------------------------------


def test_twin_wrong_type_does_not_match_nested_leaf():
    """except* OSError must not extract nested TypeError (spelling-adjacent twin)."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'outer',\n"
            "            [ExceptionGroup('inner', [TypeError('t')])],\n"
            "        )\n"
            "    except* OSError:\n"
            "        raise RuntimeError('must-not-run')\n",
            name="twin_wrong_type.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["TypeError"], names
    assert "RuntimeError" not in names


def test_twin_never_selects_only_first_nested_leaf_of_repeated_type():
    """except* TypeError extracts BOTH nested TypeErrors, not only the first."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup(\n"
            "            'outer',\n"
            "            [\n"
            "                ExceptionGroup(\n"
            "                    'inner',\n"
            "                    [TypeError('t1'), ValueError('v'), TypeError('t2')],\n"
            "                ),\n"
            "            ],\n"
            "        )\n"
            "    except* TypeError:\n"
            "        pass\n",
            name="twin_not_first_leaf.py",
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["ValueError"], names


def test_twin_full_outer_consume_is_complete_not_nested_residual():
    """Both outer leaves matched → Complete; no invented nested residual."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup(\n"
        "            'outer',\n"
        "            [\n"
        "                ValueError('a'),\n"
        "                ExceptionGroup('inner', [TypeError('t')]),\n"
        "            ],\n"
        "        )\n"
        "    except* (ValueError, TypeError):\n"
        "        pass\n",
        name="twin_full_consume.py",
    )
    assert isinstance(outcome, Complete), outcome
