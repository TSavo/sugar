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
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus


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
    assert isinstance(value_errors[0].occurrence, str) and ":" in value_errors[0].occurrence, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {value_errors[0].occurrence!r}"
    )
    assert isinstance(value_errors[1].occurrence, str) and ":" in value_errors[1].occurrence, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {value_errors[1].occurrence!r}"
    )
    assert value_errors[0].occurrence != value_errors[1].occurrence
    assert isinstance(type_errors[0].occurrence, str) and ":" in type_errors[0].occurrence, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {type_errors[0].occurrence!r}"
    )
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


def test_ordinary_try_refuses_grouped_raise_effect():
    """Ordinary except must not decide miss on GroupedRaiseEffect.

    GroupedRaiseEffect is a sibling of RaiseEffect, not a subclass. Returning
    MatchDecided(False) fabricates a miss on an effect kind ordinary Try
    cannot read. Mirror TryStarSugar: named SugarNotWritten, membrane stays
    loud both directions.
    """
    with pytest.raises(SugarNotWritten) as excinfo:
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except ValueError:\n"
            "        pass\n",
            name="ordinary_try.py",
        )
    gap = excinfo.value
    assert gap.owner == "TrySugar._effect_match_verdict"
    assert gap.observed == "GroupedRaiseEffect"
    assert "RaiseEffect" in gap.requested
    assert "except*" in gap.fix


def test_ordinary_try_except_exceptiongroup_still_refuses_without_split():
    """even except ExceptionGroup on ordinary Try does not enter TryStar partition.

    The arm still cannot read GroupedRaiseEffect through RaiseEffect matching;
    deciding miss would be the same fabricated verdict. Loud until ordinary
    Try owns grouped routing (it does not).
    """
    with pytest.raises(SugarNotWritten) as excinfo:
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except ExceptionGroup:\n"
            "        pass\n",
            name="ordinary_eg.py",
        )
    gap = excinfo.value
    assert gap.owner == "TrySugar._effect_match_verdict"
    assert gap.observed == "GroupedRaiseEffect"


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


def test_truthful_ordinary_try_still_matches_raise_effect():
    """Truthful twin: ordinary RaiseEffect under ordinary except still routes."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('alone')\n"
        "    except ValueError:\n"
        "        return 1\n",
        name="ordinary_raise_truthful.py",
    )
    assert isinstance(outcome, Complete), outcome


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


def test_grouped_raise_occurrence_is_sealed_coordinate_not_line_col_spelling():
    """Group occurrence is the sealed memento coordinate, not filename:line:col."""
    effect = _grouped_halt(
        _desugar(
            "def f():\n"
            "    raise ExceptionGroup('g', [ValueError()])\n",
            name="sealed_occ_a.py",
        )
    )
    assert isinstance(effect.occurrence, str) and ":" in effect.occurrence, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {effect.occurrence!r}"
    )
    # Sealed coordinate carries blake3 CIDs; fabricated line-col is "file:N:M".
    assert "blake3" in effect.occurrence
    assert effect.occurrence.count(":") >= 4  # file:start:end:source_cid:cid
    other = _grouped_halt(
        _desugar(
            "def f():\n"
            "    raise ExceptionGroup('g', [ValueError()])\n",
            name="sealed_occ_b.py",
        )
    )
    # Different authenticated source files differ even with identical span text.
    assert effect.occurrence != other.occurrence


# ---------------------------------------------------------------------------
# Advisor repairs: temporal threading, Returned face, guard conjunction
# ---------------------------------------------------------------------------


def _synthetic_class(name: str):
    """One shared ClassValue identity for matcher/leaf (is-subtype uses `is`)."""
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const

    identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )
    cls = ClassValue(name, (), BlockValue(()))
    typed = AuthenticatedExceptionTypeValue(cls, identity, (identity,), class_value=cls)
    return cls, typed, identity


def test_second_handler_reads_first_handler_temporal_binding():
    """Handlers execute temporally — later handler sees prior handler state.

    Fixed sugars pin TryStarSugar threading (nodes.py substitute frozen).
    ClassValue instances are shared so subtype partition uses `is` identity.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import Complete, Incomplete
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    site = SimpleNamespace(
        filename="temporal_thread.py",
        line=1,
        col=0,
        unit=SimpleNamespace(source="try-star"),
    )
    _ve_cls, ve_typed, ve_id = _synthetic_class("ValueError")
    _te_cls, te_typed, te_id = _synthetic_class("TypeError")

    ve_leaf = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of("leaf:ve"),
        exception_type_coordinate=ve_id,
        exception_type_mro=(ve_id,),
        raised_value=ve_typed,
    )
    te_leaf = RaiseEffect(
        exception_name="TypeError",
        occurrence=AuthenticatedRaiseLocus.of("leaf:te"),
        exception_type_coordinate=te_id,
        exception_type_mro=(te_id,),
        raised_value=te_typed,
    )
    group = GroupedRaiseEffect(
        "group:root", "g", (ve_leaf, te_leaf), occurrence=AuthenticatedRaiseLocus.of("group:root")
    )

    class Fixed(Sugar):
        def __init__(self, outcome):
            self.outcome = outcome

        def desugar(self, ctx=None):
            del ctx
            return self.outcome

        @classmethod
        def witnesses(cls):
            return ()

    class BindX(Sugar):
        def desugar(self, ctx=None):
            from sugar_lift_py_tests.outcome.exit_set import ExitSet

            if ctx is None:
                ctx = ReduceContext.root(owner="BindX")
            bound = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
            # ExitSet face carries _ReducedBlock.context (Complete(floor) cannot).
            return ExitSet.completed(
                _ReducedBlock(
                    entries=(),
                    can_fall_through=True,
                    fall_through=(),
                    context=bound,
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    class ReadXOrHalt(Sugar):
        def desugar(self, ctx=None):
            temporal = getattr(ctx, "temporal", None) if ctx is not None else None
            bound = temporal.value_if_bound("x") if temporal is not None else None
            if bound is None:
                return Incomplete(
                    RaiseEffect(
                        exception_name="NameError",
                        occurrence=AuthenticatedRaiseLocus.of("read-x-missing"),
                    )
                )
            return Incomplete(
                RaiseEffect(
                    exception_name="RuntimeError",
                    occurrence=AuthenticatedRaiseLocus.of("read-x-ok"),
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    class MatchType(Sugar):
        def __init__(self, typed):
            self.typed = typed

        def desugar(self, ctx=None):
            del ctx
            return Complete(self.typed)

        @classmethod
        def witnesses(cls):
            return ()

    sugar = TryStarSugar(
        body=(Fixed(Incomplete(group)),),
        handlers=(
            ((MatchType(ve_typed),), (BindX(),), "slot-ve"),
            ((MatchType(te_typed),), (ReadXOrHalt(),), "slot-te"),
        ),
        site=site,
    )
    outcome = sugar.desugar(ReduceContext.root(owner="temporal_twin"))
    # Retained faces (handler completion + exceptional regroup) collapse to a
    # linear Complete carrying Incomplete entries — project raise names from both.
    names: list[str] = []

    def collect(obj):
        if isinstance(obj, Incomplete):
            if isinstance(obj.effect, GroupedRaiseEffect):
                names.extend(leaf.exception_name for leaf in _leaves(obj.effect))
            elif isinstance(obj.effect, RaiseEffect):
                names.append(obj.effect.exception_name)
        elif isinstance(obj, Complete):
            record = getattr(obj.value, "record", obj.value)
            for stmt in getattr(record, "statements", ()) or getattr(
                record, "entries", ()
            ):
                collect(stmt)
        elif isinstance(obj, ExitSet):
            for face in obj.exits:
                if isinstance(face, Halted):
                    if isinstance(face.effect, GroupedRaiseEffect):
                        names.extend(
                            leaf.exception_name for leaf in _leaves(face.effect)
                        )
                    elif isinstance(face.effect, RaiseEffect):
                        names.append(face.effect.exception_name)

    collect(outcome)
    assert "RuntimeError" in names, (names, outcome)
    assert "NameError" not in names, names


def test_handler_terminal_return_face_is_retained_not_dropped():
    """Completed terminal return (finally override) is retained, not dropped."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError()])\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        return 7\n",
        name="handler_return_face.py",
    )
    assert isinstance(outcome, Complete), outcome
    returns = [
        s for s in outcome.value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns and returns[0].value.value == 7


def _capture_trystar_exitset(sugar, ctx):
    """Desugar TryStar but capture the ExitSet before exitset_to_outcome."""
    import sugar_lift_py_tests.sugar.exit_set_routing as esr

    captured = {}
    real = esr.exitset_to_outcome

    def capture(es):
        captured["es"] = es
        return real(es)

    esr.exitset_to_outcome = capture
    try:
        sugar.desugar(ctx)
    finally:
        esr.exitset_to_outcome = real
    assert "es" in captured
    return captured["es"]


def test_handler_pass_with_residual_is_not_a_completed_edge():
    """Handler fall-through is not a try* completed edge while residual remains.

    Python has no completed edge when except* handles part of a group and an
    unmatched subgroup continues — the residual must ultimately halt unless
    later consumed. Discriminates the false-Completed emission bug.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar
    from sugar_source_tree.nodes import TryStar

    source = (
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError:\n"
        "        pass\n"
    )
    outcome = _desugar(source, name="residual_not_complete.py")
    # Must halt with residual TypeError — never Complete at the function edge.
    assert not isinstance(outcome, Complete), outcome
    effect = _grouped_halt(outcome)
    assert [leaf.exception_name for leaf in _leaves(effect)] == ["TypeError"]

    tree = SourceFile(
        (source, "residual_faces.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    fn = list(tree.functions())[-1]

    def find_trystar(node):
        if isinstance(node, TryStar):
            return node
        for field in getattr(node, "_child_fields", ()):
            child = getattr(node, field, None)
            if isinstance(child, tuple):
                for item in child:
                    found = find_trystar(item)
                    if found is not None:
                        return found
            elif child is not None:
                found = find_trystar(child)
                if found is not None:
                    return found
        return None

    sugar = find_trystar(fn).sugar()
    assert isinstance(sugar, TryStarSugar)
    es = _capture_trystar_exitset(sugar, None)
    completed = [face for face in es.exits if isinstance(face, Completed)]
    halted = [face for face in es.exits if isinstance(face, Halted)]
    assert halted, es.exits
    # No Completed face while residual still lives.
    assert not completed, completed
    assert all(
        isinstance(face.effect, GroupedRaiseEffect)
        and [leaf.exception_name for leaf in _leaves(face.effect)] == ["TypeError"]
        for face in halted
    )


def test_guarded_handler_faces_conjoin_body_guard():
    """Handler-exit guards are conjoined with the body halt guard on THAT face."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    site = SimpleNamespace(
        filename="guard_conj.py",
        line=1,
        col=0,
        unit=SimpleNamespace(source="try-star"),
    )
    _ve_cls, ve_typed, ve_id = _synthetic_class("ValueError")
    leaf = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of("leaf:ve"),
        exception_type_coordinate=ve_id,
        exception_type_mro=(ve_id,),
        raised_value=ve_typed,
    )
    group = GroupedRaiseEffect("group:root", "g", (leaf,), occurrence=AuthenticatedRaiseLocus.of("group:root"))
    body_atom = atomic("body.guard", [str_const("body")])
    handler_atom = atomic("handler.guard", [str_const("handler")])

    class Fixed(Sugar):
        def __init__(self, outcome):
            self.outcome = outcome

        def desugar(self, ctx=None):
            del ctx
            return self.outcome

        @classmethod
        def witnesses(cls):
            return ()

    class MatchVE(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(ve_typed)

        @classmethod
        def witnesses(cls):
            return ()

    class GuardedRaise(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet(
                (
                    Halted(
                        handler_atom,
                        RaiseEffect(
                            exception_name="RuntimeError",
                            occurrence=AuthenticatedRaiseLocus.of("handler:re"),
                        ),
                        None,
                    ),
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    class BodyHalt(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet((Halted(body_atom, group, None),))

        @classmethod
        def witnesses(cls):
            return ()

    sugar = TryStarSugar(
        body=(BodyHalt(),),
        handlers=(((MatchVE(),), (GuardedRaise(),), "slot-ve"),),
        site=site,
    )
    es = _capture_trystar_exitset(sugar, ReduceContext.root(owner="guard_twin"))
    halted = [face for face in es.exits if isinstance(face, Halted)]
    assert halted, es.exits
    text = str(halted[0].guard)
    assert "body.guard" in text or "body" in text, text
    assert "handler.guard" in text or "handler" in text, text
    effect = halted[0].effect
    if isinstance(effect, RaiseEffect):
        assert effect.exception_name == "RuntimeError"
    else:
        assert any(
            leaf.exception_name == "RuntimeError" for leaf in _leaves(effect)
        )


def test_alternative_exceptional_faces_keep_separate_guards():
    """Regroup never ANDs guards from mutually exclusive exceptional exits.

    A handler that splits into two exceptional faces under g1|g2 must emit
    two residual/exception faces, each under its own guard — not one face
    under g1∧g2 (impossible).
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.ir import atomic, str_const
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

    site = SimpleNamespace(
        filename="guard_split.py",
        line=1,
        col=0,
        unit=SimpleNamespace(source="try-star"),
    )
    _ve_cls, ve_typed, ve_id = _synthetic_class("ValueError")
    leaf = RaiseEffect(
        exception_name="ValueError",
        occurrence=AuthenticatedRaiseLocus.of("leaf:ve"),
        exception_type_coordinate=ve_id,
        exception_type_mro=(ve_id,),
        raised_value=ve_typed,
    )
    group = GroupedRaiseEffect("group:root", "g", (leaf,), occurrence=AuthenticatedRaiseLocus.of("group:root"))
    body_atom = atomic("body.guard", [str_const("body")])
    g1 = atomic("alt.one", [str_const("1")])
    g2 = atomic("alt.two", [str_const("2")])

    class MatchVE(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(ve_typed)

        @classmethod
        def witnesses(cls):
            return ()

    class SplitRaise(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet(
                (
                    Halted(
                        g1,
                        RaiseEffect(exception_name="KeyError", occurrence=AuthenticatedRaiseLocus.of("a1")),
                        None,
                    ),
                    Halted(
                        g2,
                        RaiseEffect(exception_name="OSError", occurrence=AuthenticatedRaiseLocus.of("a2")),
                        None,
                    ),
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    class BodyHalt(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet((Halted(body_atom, group, None),))

        @classmethod
        def witnesses(cls):
            return ()

    sugar = TryStarSugar(
        body=(BodyHalt(),),
        handlers=(((MatchVE(),), (SplitRaise(),), "slot-ve"),),
        site=site,
    )
    es = _capture_trystar_exitset(sugar, ReduceContext.root(owner="split_twin"))
    halted = [face for face in es.exits if isinstance(face, Halted)]
    assert len(halted) >= 2, es.exits
    texts = [str(face.guard) for face in halted]
    assert any("alt.one" in t or "1" in t for t in texts), texts
    assert any("alt.two" in t or "2" in t for t in texts), texts
    if len(halted) == 1:
        raise AssertionError(f"alts collapsed into one face: {texts}")
    names = []
    for face in halted:
        if isinstance(face.effect, RaiseEffect):
            names.append(face.effect.exception_name)
        elif isinstance(face.effect, GroupedRaiseEffect):
            names.extend(leaf.exception_name for leaf in _leaves(face.effect))
    assert "KeyError" in names and "OSError" in names, names
