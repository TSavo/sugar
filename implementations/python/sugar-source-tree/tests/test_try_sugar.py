"""`try` as the STRUCTURAL surface of the effect router: except clauses match
by authenticated exception identity (the same rule with-contracts ride), matching handlers
consume the halt, non-matches propagate, else/finally splice, and the
loud residuals stay loud. Mirror of test_with_contract.py for the native-syntax
twin."""

import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_source_tree.panic import SugarNotWritten
from with_resolution_fixture import source_file_with_preconstruction


def _val(src):
    """The function's one reduction: its arms (an ``ExitSet``), through the
    entrance the lift reduces every function by (module globals bound)."""
    return function_universe_outcome(_fn(src))


def _completed(out):
    """The one unconditional completed value of ``out``."""
    value = out.completed_value()
    assert value is not None, out
    return value


def _post(out):
    return _completed(out).post()


def _invs(out):
    return _completed(out).invs()


def _record(out):
    return _completed(out).record


def _completed_val(src, callee):
    """The completed face's value where ``callee``'s own call may raise.

    ``warnings`` is not enrolled, so ``warnings.warn`` is an unknown callee: it
    completes or raises (``filterwarnings("error")`` makes it raise).
    """
    from sugar_lift_py_tests.outcome import Completed

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    exits = (
        next(source_file_with_preconstruction(Path(path)).functions())
        .sugar()
        .desugar()
        .exits
    )
    (completed,) = [face for face in exits if isinstance(face, Completed)]
    assert [
        face.effect.producer_node_owner for face in exits if face is not completed
    ] == [f"UnknownCallee:{callee}"]
    return completed.value


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def _exception_identity(function, name: str):
    occurrence = next(
        node for node in function.walk() if node.kind == "Name" and node.id == name
    )
    identity = function.unit.exception_type_identity(occurrence)
    assert identity is not None
    return identity


def _incompletes(out):
    """Every halt ``out`` leaves by: its halted arms, and the halted arms of
    the all-halting entries a completed arm's record carries."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    halts = list(out.halts())
    for face in out.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        if record is None:
            continue
        halts.extend(
            halt
            for entry in record.contribution()
            if isinstance(entry, ExitSet) and entry.halts() == entry.exits
            for halt in entry.halts()
        )
    return halts


def test_matching_except_consumes_raise_and_try_completes():
    # Matching except ValueError consumes the body's raise; the function
    # completes past the try (post out == z), same discharge shape as
    # with-raises under Suppresses/Expects consume.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_handler_own_raise_propagates():
    # A matching handler that itself raises: the body's raise is consumed, the
    # handler's raise rides out as red testimony (does not disappear).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise KeyError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "KeyError"


def test_except_keyerror_does_not_catch_valueerror():
    # Exact-match discrimination (the mismatch twin): except KeyError does NOT
    # silently catch a ValueError body -- the halt survives.
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_except_valueerror_does_catch_valueerror():
    # Positive twin of the discrimination: except ValueError consumes a
    # ValueError body raise -- zero red raises survive.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_renamed_handler_and_raise_match_by_authenticated_identity():
    """Different lexical spellings for one builtin identity still match."""
    v = _val(
        "from builtins import ValueError as Raised\n"
        "from builtins import ValueError as Caught\n"
        "def A(z):\n"
        "    try:\n"
        "        raise Raised\n"
        "    except Caught:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_source_subclass_matches_authenticated_base_coordinate():
    """A source-derived MRO, not a spelling relation, proves the catch."""
    v = _val(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "def A(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except RootFault:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_source_unrelated_handler_propagates_by_authenticated_mro():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "class OtherFault(Exception):\n"
        "    pass\n"
        "def A(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except OtherFault:\n"
        "        pass\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)


def test_same_spelling_unresolved_handler_identity_is_retained_not_decided():
    """A formal named E is not exception authority on either side.

    Neither operand has an authenticated identity, so the match is the
    retained question ``adt.is_python_type(raised, handler)``
    (``authenticated_exception_matching``): the same spelling never decides
    it, and the miss face still raises.  (It once refused by name; main
    carries the undecided question instead, #7757.)"""
    out = _val(
        "def A(E):\n"
        "    try:\n"
        "        raise E\n"
        "    except E:\n"
        "        pass\n"
    )
    assert "adt.is_python_type" in repr(out)
    assert _incompletes(out), "the miss face of the retained match must still raise"


def test_unresolved_raised_identity_is_retained_not_decided_at_the_router():
    """Formal ``raise E`` vs typed ``except ValueError`` is MatchRetained.

    ``matches_raise_effect`` retains ``adt.is_python_type(E, ValueError)`` when
    both operands have value terms but no authenticated exception identity.
    That is not a construction gap and not a silent match/miss: both faces of
    the partition must survive. ObservedEffectBinding rides under the match
    arm guard without inventing a second occurrence.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.effect_router import ObservedEffectBinding
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import ExitSet

    out = (
        _fn(
            "def A(E):\n"
            "    try:\n"
            "        raise E\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    value = out.completed_value()
    assert isinstance(value, UniverseValue)
    record = value.record
    # Residual halt under the open type test (miss face).
    residual = tuple(
        halt
        for entry in record.statements
        if isinstance(entry, ExitSet) and entry.halts() == entry.exits
        for halt in entry.halts()
        if isinstance(halt.effect, RaiseEffect)
    )
    assert residual, "miss face of retained identity must remain a raise"
    # Match-arm binding testimony must not invent TypeError / RuntimeEffect.
    bindings = tuple(
        entry for entry in record.statements if isinstance(entry, ObservedEffectBinding)
    )
    assert all(isinstance(b.effect, RaiseEffect) for b in bindings)
    text = str(out)
    assert "adt.is_python_type" in text
    assert "TypeError" not in text
    assert "RuntimeEffect" not in text


def test_bare_reraise_reemits_the_exact_inflight_raise():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    function = _fn(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise\n"
    )
    out = function.sugar().desugar()
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_type_coordinate == _exception_identity(
        function, "ValueError"
    )
    assert halt.effect.exception_name == "ValueError"
    assert halt.effect.occurrence.value.endswith(":6:8")


def test_nested_bare_reraise_uses_the_nearest_handler_slot():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import ExitSet

    out = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except ValueError:\n"
            "        try:\n"
            "            raise KeyError\n"
            "        except KeyError:\n"
            "            raise\n"
        )
        .sugar()
        .desugar()
    )
    if out.exits and out.halts() == out.exits:
        effects = tuple(halt.effect for halt in out.halts())
    else:
        value = out.completed_value()
        assert value is not None, out
        effects = tuple(
            halt.effect
            for entry in value.record.contribution()
            if isinstance(entry, ExitSet) and entry.halts() == entry.exits
            for halt in entry.halts()
        )
    assert len(effects) == 1
    assert isinstance(effects[0], RaiseEffect)
    assert effects[0].exception_name == "KeyError"
    assert effects[0].occurrence.value.endswith(":9:12")


def test_handler_effect_slots_are_content_addressed_occurrences():
    fn = _fn(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    handlers = [node for node in fn.walk() if node.kind == "ExceptHandler"]
    slots = [handler._effect_slot_id() for handler in handlers]
    assert all(slot.startswith("blake3-512:") for slot in slots)
    assert slots[0] != slots[1]
    assert slots == [handler._effect_slot_id() for handler in handlers]


def test_else_runs_when_body_is_raise_free():
    # Body with no observed raise reduces else; the else return is the exit.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_else_does_not_run_when_raise_is_caught():
    # Caught raise takes the handler path, not else: handler return wins.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return z\n"
        "    else:\n"
        "        return 0\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_finally_reduces_on_caught_path():
    # finally always runs: after a matching except, finally's return is the
    # exit (Python: finally return is the function exit).
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_finally_reduces_on_uncaught_path():
    # Cleanup halt supersedes the incoming uncaught raise (Python: only
    # RuntimeError propagates; ValueError does not also ride).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    finally:\n"
        "        raise RuntimeError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    names = {r.effect.exception_name for r in reds if isinstance(r.effect, RaiseEffect)}
    assert names == {"RuntimeError"}


def test_finally_pass_restores_uncaught_raise():
    """Cleanup fall-through restores the incoming halt (ValueError survives)."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    finally:\n"
        "        z = z\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_finally_return_supersedes_caught_path():
    """Return in finally is the function exit after a matching except."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        x = 1\n"
        "    finally:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_finally_on_normal_completion():
    """finally runs on the no-raise path; fall-through keeps body completion."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        x = z\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_conditional_raise_both_exits_survive_through_finally():
    """Pressure twin: body -> ExitSet -> route Halted -> finally over every exit.

    ``if c: raise`` / ``return 1`` / ``except: return 2`` / ``finally`` must keep
    both guarded completions — not consume the raise into an unconditional
    handler while only the ¬c return rides as residual testimony.
    """
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    finally:\n"
        "        y = 0\n"
    )
    assert _incompletes(v) == []
    # Same dual post shape as ``if c: return 2\\nelse: return 1``.
    ideal = _val(
        "def A(c):\n"
        "    if c:\n"
        "        return 2\n"
        "    else:\n"
        "        return 1\n"
    )
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.ir import not_

    returns = [e for e in _record(v).contribution() if isinstance(e, GuardedReturn)]
    assert len(returns) == 2
    assert {entry.value.value for entry in returns} == {1, 2}
    assert returns[1].guards[0] == not_(returns[0].guards[0])
    values = {r.value.value for r in returns}
    assert values == {1, 2}


def test_conditional_raise_assign_paths_through_finally_no_residual_halt():
    """User surface: assign on both faces + cleanup; raise must not leak red.

    Temporal phi for ``x`` across try/except is separate substitute work; this
    twin locks that conditional routing + finally does not leave a bare raise.
    """
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        x = 2\n"
        "    finally:\n"
        "        y = 0\n"
        "    return x\n"
    )
    assert _incompletes(v) == []
    post = _post(v)
    assert post.kind == "and"
    assert {face.operands[1].args[1].value for face in post.operands} == {1, 2}
    by_value = {
        face.operands[1].args[1].value: face.operands[0] for face in post.operands
    }
    assert by_value[2].name == "py.truthy"
    assert by_value[1].kind == "not"


def test_finally_fallthrough_preserves_break_for_the_matching_loop():
    """Cleanup runs on break, then the loop alone consumes its owned halt."""
    v = _val(
        "def A():\n"
        "    for item in [1]:\n"
        "        try:\n"
        "            break\n"
        "        finally:\n"
        "            marker = item\n"
        "    return marker\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].value == 1


def test_finally_fallthrough_preserves_continue_for_the_matching_loop():
    """Cleanup runs on continue before the matching loop routes its latch."""
    v = _val(
        "def A():\n"
        "    for item in [1]:\n"
        "        try:\n"
        "            continue\n"
        "        finally:\n"
        "            marker = item\n"
        "    return marker\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].value == 1


def test_finally_raise_supersedes_break_instead_of_fabricating_loop_exit():
    """A cleanup halt supersedes the incoming break face."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    function = _fn(
        "class ArbitraryCleanupFault(Exception):\n"
        "    pass\n"
        "def A():\n"
        "    for item in [1]:\n"
        "        try:\n"
        "            break\n"
        "        finally:\n"
        "            raise ArbitraryCleanupFault\n"
        "    return 11\n"
    )
    out = function.sugar().desugar()
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_type_coordinate == _exception_identity(
        function, "ArbitraryCleanupFault"
    )
    assert halt.effect.exception_name == "ArbitraryCleanupFault"


def test_finally_return_supersedes_break_exit():
    """A terminal cleanup completion replaces the incoming break face."""
    v = _val(
        "def A():\n"
        "    for item in [1]:\n"
        "        try:\n"
        "            break\n"
        "        finally:\n"
        "            return 13\n"
        "    return 0\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].value == 13


def test_nested_exception_group_constructs_tree_without_flattening():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    raise ExceptionGroup('outer', [\n"
            "        ValueError(),\n"
            "        ExceptionGroup('inner', [TypeError(), KeyError()]),\n"
            "    ])\n"
        )
        .sugar()
        .desugar()
    )

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert len(halt.effect.children) == 2
    assert isinstance(halt.effect.children[0], RaiseEffect)
    nested = halt.effect.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert len(nested.children) == 2
    assert all(isinstance(item, RaiseEffect) for item in nested.children)
    occurrences = tuple(item.occurrence_id for item in nested.children)
    assert occurrences[0] != occurrences[1]


def test_except_star_partitions_nested_group_and_propagates_only_residual():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('outer', [TypeError(), ExceptionGroup('inner', [ValueError(), KeyError()])])\n"
            "    except* ValueError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    residual = halt.effect
    assert isinstance(residual, GroupedRaiseEffect)
    assert isinstance(residual.children[0], RaiseEffect)
    assert residual.children[0].exception_name == "TypeError"
    nested = residual.children[1]
    assert isinstance(nested, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in nested.children] == ["KeyError"]


def test_except_star_residual_flows_to_subsequent_handlers():
    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        pass\n"
            "    except* TypeError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.completed_value() is not None


def test_except_star_bare_reraise_regroups_original_tree():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        raise\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in halt.effect.children] == [
        "ValueError",
        "TypeError",
    ]


def test_except_star_never_selects_only_first_leaf():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [TypeError(), ValueError(), ValueError()])\n"
            "    except* ValueError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in halt.effect.children] == ["TypeError"]


def test_except_star_matches_renamed_source_subclass_by_mro_identity():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "class Renamed(ValueError):\n"
            "    pass\n"
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [Renamed(), TypeError()])\n"
            "    except* ValueError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert outcome.halts() == outcome.exits
    # ``Renamed()`` is a class call: the one call edge, which may raise (its
    # ``__init__`` is joined at prove, never run here), so its own
    # undetermined halt rides beside the group's.  The group is the one halt
    # whose residual is decided by the source MRO.
    (halt,) = [h for h in outcome.halts() if isinstance(h.effect, GroupedRaiseEffect)]
    assert [leaf.exception_name for leaf in halt.effect.children] == ["TypeError"]
    assert all(
        isinstance(h.effect, UndeterminedRaiseEffect)
        for h in outcome.halts()
        if h is not halt
    )


def test_except_star_handler_raise_regroups_with_unmatched_residual():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* ValueError:\n"
            "        raise KeyError()\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert isinstance(halt.effect.children[0], RaiseEffect)
    assert halt.effect.children[0].exception_name == "KeyError"
    assert isinstance(halt.effect.children[1], GroupedRaiseEffect)


def test_shadowed_exception_group_spelling_does_not_construct_group_effect():
    """``ExceptionGroup`` here is the module global the assignment bound, read
    through the entrance every function is reduced by (its module globals
    bound, ``function_universe_outcome``): a call of it is no group
    construction, whatever its spelling."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import (
        RaiseEffect,
        UndeterminedRaiseEffect,
    )

    outcome = _val(
        "ExceptionGroup = lambda message, members: ValueError()\n"
        "def A():\n"
        "    raise ExceptionGroup('g', [ValueError()])\n"
    )
    assert outcome.halts() and outcome.halts() == outcome.exits
    for halt in outcome.halts():
        assert isinstance(halt.effect, (RaiseEffect, UndeterminedRaiseEffect))
        assert not isinstance(halt.effect, GroupedRaiseEffect)


def test_ordinary_except_does_not_consume_grouped_raise():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)


def test_warnings_warn_with_an_explicit_category_mints_authenticated_testimony():
    """This test previously pinned the ABSENCE of a source producer.

    It was right when it was written -- nothing in any ``src`` tree constructed
    a ``WarningObservationValue``, so the consumer shipped in ``dd3d1b5ca``
    (#6458) had no other half. The producer now exists, so the absence it
    asserted is no longer the truth about this source, and pinning it would
    keep the gap green. What replaces it is the same claim in the positive
    direction: an EXPLICIT source-written category authenticates, and its
    coordinate is the ordinary ``python:exception_type_identity`` the
    raise/except projection already mints -- no warning vocabulary is added.
    """
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const

    v = _completed_val(
        "import warnings\n" "def A():\n" "    warnings.warn('message', UserWarning)\n",
        "warnings.warn",
    )
    entries = v.record.contribution()
    observations = [
        entry for entry in entries if isinstance(entry, WarningObservationValue)
    ]
    assert len(observations) == 1
    assert observations[0].effect.category_identity == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("UserWarning")],
    )
    assert observations[0].guards == ()


def test_warnings_warn_without_a_category_still_fabricates_nothing():
    """``warnings.warn(msg)`` defaults to ``UserWarning`` in CPython, not in the
    source text. Inferring it here would put an unstated assumption inside an
    authenticated coordinate, so the call stays an ordinary unresolved site --
    which the completed-face boundary names, rather than reading as "no
    warning". This is the half of the old test that is still true."""
    from sugar_lift_py_tests.effect.warning_effect import WarningEffect
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )

    v = _completed_val(
        "import warnings\n" "def A():\n" "    warnings.warn('message')\n",
        "warnings.warn",
    )
    entries = v.record.contribution()
    calls = [entry for entry in entries if isinstance(entry, CallSiteValue)]
    assert len(calls) == 1
    assert calls[0].target_contract_cid is None
    assert not any(isinstance(entry, WarningObservationValue) for entry in entries)
    assert not any(
        isinstance(getattr(entry, "effect", None), WarningEffect) for entry in entries
    )


def test_false_arm_conditional_raise_routes_with_reverse_polarity():
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            pass\n"
        "        else:\n"
        "            raise ValueError\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        x = 2\n"
        "    return x\n"
    )
    assert _incompletes(v) == []
    post = _post(v)
    assert post.kind == "and"
    by_value = {
        face.operands[1].args[1].value: face.operands[0] for face in post.operands
    }
    assert by_value[1].name == "py.truthy"
    assert by_value[2].kind == "not"


def test_except_as_binds_matching_raise_witness_in_handler():
    # Tree rewrites `error` → EffectRef(slot); routing emits EffectBinding facts.
    # Coordinate stays effect-slot(S); identity lives in constructed testimony.
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as error:\n"
        "        return error\n"
    )
    assert _incompletes(v) == []
    post = _post(v)
    assert post.args[0].name == "out"
    assert post.args[1].name == "python:effect_slot"
    # Authentication is explicit record testimony (not ambient seal).
    inv_names = [inv.name for inv in _invs(v)]
    assert "effect_slot_type" in inv_names or any(
        getattr(inv, "name", None) == "effect_slot_type"
        or (hasattr(inv, "args") and inv.name == "=")
        for inv in _invs(v)
    )
    # Find effect_slot_type fact: atomic effect_slot_type(S) = "ValueError"
    typed = [
        inv
        for inv in _invs(v)
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert (
        typed
    ), f"missing effect_slot_type in {[i.name for i in _invs(v)]}: {_invs(v)}"
    assert typed[0].args[1].value == "ValueError"
    # Witness identity is the slot itself (post), not a type-derived equation.
    assert not any(
        inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_identity"
        for inv in _invs(v)
    )
    origins = [
        inv
        for inv in _invs(v)
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_origin"
    ]
    assert origins, "effect_slot_origin must link slot to raise occurrence"
    assert origins[0].args[1].name == "python:raise_effect_occurrence"


def test_except_as_bound_name_observes_the_routed_effect_identity():
    """``as error`` observes the same RaiseEffect the handler routed.

    Nested raise under an active handler installs ``context_effect`` on the
    inner halt. Returning ``error.__context__`` is only well-defined when
    EffectRef projected that exact routed effect (ObservedEffectValue), not a
    pure EffectCoordinate. The lying path (coordinate without preimage) is
    pinned unit-side; here the truthful source path must complete.
    """

    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ImportError\n"
        "    except ImportError:\n"
        "        try:\n"
        "            raise ValueError\n"
        "        except ValueError as error:\n"
        "            return error.__context__\n"
    )
    assert _incompletes(v) == []
    post = _post(v)
    # __context__ of the routed ValueError is the handled ImportError's
    # raised value — a constructed exception coordinate, not the slot itself.
    assert post.args[0].name == "out"
    assert post.args[1].name != "python:effect_slot"
    # No residual incomplete from a missing context preimage.
    from sugar_lift_py_tests.outcome import ExitSet

    assert not any(
        isinstance(e, ExitSet) and e.exits and e.halts() == e.exits
        for e in _record(v).contribution()
    )


def test_except_as_does_not_bind_on_uncaught_path():
    # Wrong-type handler is unreachable; its EffectRef is never authenticated.
    # Body raise propagates (mismatch twin).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError as error:\n"
        "        return error\n"
        "    return 0\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_tuple_except_catches_any_exactly_listed_type():
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, ValueError):\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_tuple_except_does_not_catch_unlisted_type():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, IndexError):\n"
        "        pass\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_tuple_except_as_binds_the_matched_type_witness():
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, ValueError) as error:\n"
        "        return error\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "python:effect_slot"
    typed = [
        inv
        for inv in _invs(v)
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert typed and typed[0].args[1].value == "ValueError"


def test_bare_except_catches_arbitrary_raise():
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ArbitraryProjectHalt\n"
        "    except:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def test_except_star_matches_an_ordinary_raise_as_its_one_member_group():
    """``except*`` over a plain ``raise``: CPython matches the exception as
    the one-member group (``try_star_sugar``), so ``except* ValueError``
    consumes it and the function goes on.  (It once refused by name.)"""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert _post(v).args[1].name == "z"


def _never_completes(out):
    from sugar_lift_py_tests.outcome import Completed

    assert out.exits, out
    assert not any(isinstance(face, Completed) for face in out.exits), out


def test_non_name_except_type_never_consumes_the_raise():
    """``except exception_type():`` with ``exception_type`` bound nowhere:
    evaluating the handler type reads a name every read of which raises
    ``NameError`` (``SourceUnit.name_bound_nowhere``), so nothing consumes
    the raise and no face completes.  (It once refused by name.)"""
    _never_completes(
        _val(
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except exception_type():\n"
            "        pass\n"
            "    return z\n"
        )
    )


def test_dotted_except_without_authenticated_import_identity_never_matches():
    """Equal dotted spelling is not exception authority: ``os`` is bound
    nowhere, so ``raise os.error`` and ``except os.error`` each read a
    ``NameError``, and the equal spelling never consumes a raise.  (It once
    refused by name.)"""
    _never_completes(
        _val(
            "def A(z):\n"
            "    try:\n"
            "        raise os.error\n"
            "    except os.error:\n"
            "        pass\n"
            "    return z\n"
        )
    )


def test_two_raise_valueerror_sites_have_distinct_origins_same_type():
    """Two raise ValueError sites: equal type testimony, distinct origins."""
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as first:\n"
        "        a = first\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as second:\n"
        "        return (a, second)\n"
    )
    assert _incompletes(v) == []
    types = [
        inv.args[1].value
        for inv in _invs(v)
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert types.count("ValueError") >= 2
    origins = [
        inv.args[1].args[0].value
        for inv in _invs(v)
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_origin"
    ]
    assert len(origins) >= 2
    assert len(set(origins)) == len(origins), f"origins must be distinct: {origins}"


def test_except_star_type_tuple_partitions_every_listed_type():
    """`except* (A, B)` nets both A and B; only the unlisted leaf survives."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError(), KeyError()])\n"
            "    except* (ValueError, TypeError):\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in halt.effect.children] == ["KeyError"]


def test_except_star_type_tuple_runs_its_body_exactly_once():
    """The lying twin: one handler, one body run, however many types matched.

    An implementation that expands `except* (A, B)` into one handler spec per
    type -- which is honest for ordinary `except (A, B)` -- enters this body
    twice on a group carrying both, and the raised RuntimeError appears twice.
    Counting the leaf is what discriminates; the residual alone does not.
    """
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
            "    except* (ValueError, TypeError):\n"
            "        raise RuntimeError()\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    names = [leaf.exception_name for leaf in halt.effect.children]
    assert names == ["RuntimeError"], names


def test_except_star_type_tuple_binds_one_group_of_all_matched_leaves():
    """A bare re-raise regroups BOTH matched leaves, in original topology."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError(), TypeError(), KeyError()])\n"
            "    except* (ValueError, TypeError):\n"
            "        raise\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in halt.effect.children] == [
        "ValueError",
        "TypeError",
        "KeyError",
    ]


def test_except_star_type_tuple_with_no_matching_leaf_stays_whole():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    outcome = (
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [KeyError()])\n"
            "    except* (ValueError, TypeError):\n"
            "        pass\n"
        )
        .sugar()
        .desugar()
    )
    assert outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert [leaf.exception_name for leaf in halt.effect.children] == ["KeyError"]


def test_except_star_empty_type_tuple_stays_loud():
    """An empty tuple has no honest matcher: refuse by name, never match all."""
    with pytest.raises(SugarNotWritten) as excinfo:
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except* ():\n"
            "        pass\n"
        ).sugar()
    assert "unsupported except* handler type" in str(excinfo.value)


def test_except_star_computed_type_in_tuple_stays_loud():
    with pytest.raises(SugarNotWritten) as excinfo:
        _fn(
            "def A():\n"
            "    try:\n"
            "        raise ExceptionGroup('g', [ValueError()])\n"
            "    except* (ValueError, tm.Other):\n"
            "        pass\n"
        ).sugar()
    assert "unsupported except* handler type" in str(excinfo.value)
