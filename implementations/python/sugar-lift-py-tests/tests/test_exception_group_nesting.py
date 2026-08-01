"""Exception-group nesting — TryStar composes across two levels.

Laws:

1. Nested ``ExceptionGroup`` construction keeps topology (no flatten).
2. Outer ``except*`` partitions nested groups; residual keeps nested shape.
3. Nested ``TryStar`` inside an outer ``except*`` handler partitions the
   inner group; outer residual continues and regroups.
4. Leaf occurrence identities survive two levels — residual leaves equal the
   authenticated original sealed raise-site occurrences (not mere distinctness).
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


def _leaf_occurrence_map(effect) -> dict[str, list[str]]:
    """Map exception_name -> ordered occurrence list for all leaves."""
    by_name: dict[str, list[str]] = {}
    for leaf in _leaves(effect):
        assert isinstance(leaf.occurrence, str) and ":" in leaf.occurrence, (
            "authenticated raise locus must be a file:line:col occurrence id, "
            f"not presence-only; got {leaf.occurrence!r}"
        )
        by_name.setdefault(leaf.exception_name, []).append(leaf.occurrence)
    return by_name


def _assert_residual_preserves_original_occurrences(
    *, original: GroupedRaiseEffect, residual: GroupedRaiseEffect, names: list[str]
) -> None:
    """Each residual leaf keeps the authenticated original occurrence identity.

    Compares residual leaf occurrences to the construction-only group for the
    same sealed raise sites (line-aligned sources, same filename) — not mere
    non-null/distinctness.
    """
    orig_map = _leaf_occurrence_map(original)
    res_map = _leaf_occurrence_map(residual)
    for name in names:
        assert name in orig_map, (name, orig_map)
        assert name in res_map, (name, res_map)
        # Every residual occurrence of this type must be one of the originals
        # (routed subgroup retains the sealed raise-site identity).
        for occ in res_map[name]:
            assert occ in orig_map[name], (
                f"residual {name} occurrence {occ!r} not in original "
                f"{orig_map[name]!r} — partition must preserve authenticated "
                f"source occurrence identity, not mint a new site"
            )
        # Count: residual cannot invent extra leaves of this type.
        assert len(res_map[name]) <= len(orig_map[name]), (name, res_map, orig_map)


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
    # Line-aligned construction twin (``if True`` pads to the same raise line
    # as ``try``) so residual leaf occurrences can equal sealed originals.
    name = "outer_part_nested.py"
    raise_body = (
        "        raise ExceptionGroup(\n"
        "            'outer',\n"
        "            [\n"
        "                ValueError('a'),\n"
        "                ExceptionGroup('inner', [TypeError('t'), KeyError('k')]),\n"
        "            ],\n"
        "        )\n"
    )
    original = _grouped_halt(
        _desugar("def f():\n    if True:\n" + raise_body, name=name)
    )
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            + raise_body
            + "    except* TypeError:\n"
            "        pass\n",
            name=name,
        )
    )
    assert isinstance(effect.children[0], RaiseEffect)
    assert effect.children[0].exception_name == "ValueError"
    nested = effect.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in nested.children] == ["KeyError"]
    # Authenticated original occurrence identity — not merely non-null/distinct.
    _assert_residual_preserves_original_occurrences(
        original=original, residual=effect, names=["ValueError", "KeyError"]
    )
    # Nested residual KeyError is the same sealed raise-site as construction.
    orig_ke = [leaf for leaf in _leaves(original) if leaf.exception_name == "KeyError"]
    assert nested.children[0].occurrence == orig_ke[0].occurrence


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
# Occurrence identities survive two levels (authenticated originals)
# ---------------------------------------------------------------------------


def test_occurrence_identities_survive_two_level_partition():
    """Residual leaves keep the sealed original raise-site occurrences.

    Construction twin (line-aligned, same filename) is the authenticated
    original; residual after except* TypeError must equal those originals for
    ValueError and KeyError — not merely non-null/distinct.
    """
    name = "occ_two_level.py"
    raise_body = (
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
    )
    original = _grouped_halt(
        _desugar("def f():\n    if True:\n" + raise_body, name=name)
    )
    residual = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            + raise_body
            + "    except* TypeError:\n"
            "        pass\n",
            name=name,
        )
    )
    leaves = _leaves(residual)
    names = [leaf.exception_name for leaf in leaves]
    assert names == ["ValueError", "KeyError"], names
    _assert_residual_preserves_original_occurrences(
        original=original, residual=residual, names=["ValueError", "KeyError"]
    )
    # Extracted TypeErrors are gone; their original occurrences are not on residual.
    orig_te = _leaf_occurrence_map(original)["TypeError"]
    assert len(orig_te) == 2
    res_occs = {leaf.occurrence for leaf in leaves}
    assert not any(occ in res_occs for occ in orig_te), (orig_te, res_occs)
    # Twin: residual KeyError is not a new site at the except* line.
    assert "except*" not in (leaves[1].occurrence or "")
    assert leaves[1].occurrence == _leaf_occurrence_map(original)["KeyError"][0]


def test_bare_reraise_at_inner_level_preserves_inner_occurrences_with_outer_residual():
    """Inner bare re-raise restores authenticated inner leaf occurrences.

    Outer TypeError residual keeps its outer construction occurrence; KeyError
    (re-raised) and OSError keep the inner group's sealed raise-site identities
    (filename:line:col of the original raise constructors).
    """
    name = "inner_bare_reraise.py"
    composed = (
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
        "    except* ValueError:\n"
        "        try:\n"
        "            raise ExceptionGroup(\n"
        "                'inner', [KeyError('k'), OSError('o')]\n"
        "            )\n"
        "        except* KeyError:\n"
        "            raise\n"
    )
    # Construction-only outer, line-aligned with composed outer raise (line 3).
    outer_original = _grouped_halt(
        _desugar(
            "def f():\n"
            "    if True:\n"
            "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n",
            name=name,
        )
    )
    effect = _grouped_halt(_desugar(composed, name=name))
    leaves = _leaves(effect)
    names = [leaf.exception_name for leaf in leaves]
    assert "KeyError" in names and "OSError" in names and "TypeError" in names, names
    assert "ValueError" not in names, names

    # Sealed raise-site lines from the composed source (authenticated originals).
    lines_by_ctor: dict[str, int] = {}
    for i, line in enumerate(composed.splitlines(), 1):
        for ctor in ("KeyError(", "OSError(", "TypeError("):
            if ctor in line:
                lines_by_ctor[ctor[:-1]] = i

    by_name = {leaf.exception_name: leaf for leaf in leaves}
    for ctor_name, line in lines_by_ctor.items():
        leaf = by_name[ctor_name]
        assert isinstance(leaf.occurrence, str) and ":" in leaf.occurrence, (
            "authenticated raise locus must be a file:line:col occurrence id, "
            f"not presence-only; got {leaf.occurrence!r}"
        )
        assert leaf.occurrence.startswith(f"{name}:{line}:"), (
            f"{ctor_name} occurrence {leaf.occurrence!r} must be the sealed "
            f"raise site at {name}:{line}, not a reminted residual site"
        )

    # Outer residual TypeError equals construction-only outer original.
    outer_te = _leaf_occurrence_map(outer_original)["TypeError"][0]
    assert by_name["TypeError"].occurrence == outer_te
    assert len({leaf.occurrence for leaf in leaves}) == 3


# ---------------------------------------------------------------------------
# Twins
# ---------------------------------------------------------------------------


def test_twin_wrong_type_preserves_original_nested_group():
    """except* OSError must not touch nested TypeError — whole nested group remains.

    Preserves outer→inner topology and the authenticated TypeError raise-site
    occurrence from the construction twin (line-aligned, same filename).
    """
    name = "twin_wrong_type.py"
    raise_body = (
        "        raise ExceptionGroup(\n"
        "            'outer',\n"
        "            [ExceptionGroup('inner', [TypeError('t')])],\n"
        "        )\n"
    )
    original = _grouped_halt(
        _desugar("def f():\n    if True:\n" + raise_body, name=name)
    )
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            + raise_body
            + "    except* OSError:\n"
            "        raise RuntimeError('must-not-run')\n",
            name=name,
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["TypeError"], names
    assert "RuntimeError" not in names
    # Original nested group topology preserved (not flattened to a bare leaf).
    assert len(effect.children) == 1
    assert isinstance(effect.children[0], GroupedRaiseEffect)
    assert len(effect.children[0].children) == 1
    assert isinstance(effect.children[0].children[0], RaiseEffect)
    assert effect.children[0].children[0].exception_name == "TypeError"
    _assert_residual_preserves_original_occurrences(
        original=original, residual=effect, names=["TypeError"]
    )
    # Nested group content identity retained (segment CID); byte-span occurrence
    # of the group node may differ across line-aligned wrappers — leaf sites
    # are the load-bearing authenticated originals (asserted above).
    assert effect.children[0].group_identity == original.children[0].group_identity


def test_twin_never_selects_only_first_nested_leaf_of_repeated_type():
    """except* TypeError extracts BOTH nested TypeErrors, not only the first."""
    name = "twin_not_first_leaf.py"
    raise_body = (
        "        raise ExceptionGroup(\n"
        "            'outer',\n"
        "            [\n"
        "                ExceptionGroup(\n"
        "                    'inner',\n"
        "                    [TypeError('t1'), ValueError('v'), TypeError('t2')],\n"
        "                ),\n"
        "            ],\n"
        "        )\n"
    )
    original = _grouped_halt(
        _desugar("def f():\n    if True:\n" + raise_body, name=name)
    )
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    try:\n"
            + raise_body
            + "    except* TypeError:\n"
            "        pass\n",
            name=name,
        )
    )
    names = [leaf.exception_name for leaf in _leaves(effect)]
    assert names == ["ValueError"], names
    # Residual ValueError is the authenticated original leaf occurrence.
    _assert_residual_preserves_original_occurrences(
        original=original, residual=effect, names=["ValueError"]
    )
    # Both TypeError original sites are gone from residual.
    orig_te = set(_leaf_occurrence_map(original)["TypeError"])
    res_occs = {leaf.occurrence for leaf in _leaves(effect)}
    assert orig_te.isdisjoint(res_occs), (orig_te, res_occs)


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


def test_nested_handler_preserves_temporal_bindings_across_inner_try_star():
    """Outer except* binding remains visible after nested TryStar fully consumes.

    Pins temporal state through two handler levels: ``y`` assigned before the
    nested TryStar is still returned from the outer except* after the inner
    except* completes (and outer TypeError residual is drained).
    """
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
        "    except* ValueError:\n"
        "        y = 1\n"
        "        try:\n"
        "            raise ExceptionGroup('inner', [KeyError('k')])\n"
        "        except* KeyError:\n"
        "            z = 2\n"
        "        return y\n"
        "    except* TypeError:\n"
        "        pass\n",
        name="nested_temporal_y.py",
    )
    assert isinstance(outcome, Complete), outcome
    returns = [
        s for s in outcome.value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, outcome.value.record.statements
    assert returns[0].value.value == 1

    # Inner-handler binding used inside the nested except* (same arm).
    outcome_z = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('outer', [ValueError('a'), TypeError('b')])\n"
        "    except* ValueError:\n"
        "        try:\n"
        "            raise ExceptionGroup('inner', [KeyError('k')])\n"
        "        except* KeyError:\n"
        "            z = 2\n"
        "            return z\n"
        "    except* TypeError:\n"
        "        pass\n",
        name="nested_temporal_z.py",
    )
    assert isinstance(outcome_z, Complete), outcome_z
    returns_z = [
        s for s in outcome_z.value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns_z and returns_z[0].value.value == 2
