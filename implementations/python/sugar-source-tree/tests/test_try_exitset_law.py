"""Law twins for Try/ExitSet. Gate discharged: twins-only, no production capability.

Merged as #6242. The staging gate was discharged on the ruling that this file
is twins-only, changes no production behavior, and that ``Try`` already rode the
shared ``ExitSet`` algebra it pins here.

``Try`` is **not** a third control model.  It inherits the same ``ExitSet``
algebra ``Store`` established and ``With`` rode:

    body
      → reduce_block_to_exitset  (the shared reducer)
      → promote_raise_halts      (the shared Completed/Halted promotion)
      → handler routing over Halted arms, ``else`` over Completed arms
      → ExitSet.and_finally      (the shared cleanup fold)

Every combinator above is shared.  ``TrySugar`` contributes a matcher and an
arm-selection loop; it contributes **no sequencing**.

The six-line law::

    body Completed      → else → finally
    body matched Halt   → handler → finally
    body unmatched Halt → finally → re-propagate
    handler Halt        → finally → re-propagate
    finally completes   → preserve incoming exit
    finally terminates  → override incoming exit

Laws pinned here, each with a discrimination arm that bites:

- handlers tested in source order; only the first matching arm executes
  (bite: feed the router the reversed arm tuple, the other body is selected)
- ``as`` binds the routed effect slot, never a reconstruction
- ``else`` runs over completed edges only
  (two-sided: adding ``else`` is a no-op on an all-halt body and *does*
  change the arms on a body that completes)
- ``finally`` on all seven exits (completion, return, uncaught raise, handled
  halt, handler halt, break, continue)
- ``finally`` that terminates OVERRIDES the incoming exit -- return-in-finally
  over a halt, raise-in-finally over a halt, raise-in-finally over a
  completion (bite: force ``cleanup_restores`` to the always-restores default
  and the overridden halt comes back)
- bare re-raise preserves the same effect occurrence; no reconstruction
- no invented fall-through; no vendor arms
- ``except*`` stays separately loud, and an ordinary ``except`` never absorbs
  or rewrites a grouped raise
- **structural**: ``try/finally`` reaches the *shared* ``ExitSet.and_finally``,
  consulted exactly once, and is handed BOTH edges of the body partition
  (bite: swap in a behaviour-identical private fold -- every behavioural twin
  stays green and only the routing law goes red)
- **same instrument**: a ``try`` body and its equivalent plain spelling read
  through the same reducer produce identical arm structure, and a matched halt
  is replaced by exactly the handler body's own arms

CLOSED (#6283, repaired in #6284): the gap this file deliberately left
unpinned -- a binding established in the ``try`` body before the raise not
being visible in the handler, because ``handler_scope`` was the pre-try scope
in ``sugar_source_tree.nodes.Try.substitute`` -- is repaired.  The handler now
begins from the temporal state its routed halt edge carries.  The law and its
nine twins live in ``test_try_handler_temporal_state.py``; the control algebra
pinned here was never the defect and is unchanged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_source_tree.panic import SugarNotWritten
from with_resolution_fixture import source_file_with_preconstruction


def _identity(name: str):
    from sugar_lift_py_tests.floor.ground_exit import (
        _builtin_exception_identity,
    )

    identity, _mro = _builtin_exception_identity(name)
    return identity


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def _val(src: str):
    return _fn(src).sugar().desugar().value


def _out(src: str):
    return _fn(src).sugar().desugar()


def _incompletes(v):
    from sugar_lift_py_tests.outcome import Incomplete

    return [e for e in v.record.contribution() if isinstance(e, Incomplete)]


# ---------------------------------------------------------------------------
# Handlers: source order + first match only
# ---------------------------------------------------------------------------


def test_handlers_tried_in_source_order_first_match_only():
    """Source-order arms: base before leaf — first match wins, second never runs.

    Uses a source-derived MRO (not incomplete builtin Exception/ValueError MRO)
    so the twin pins router order, not authentication residual.
    """
    v = _val(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "def A(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except RootFault:\n"
        "        return 1\n"
        "    except LeafFault:\n"
        "        return 2\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].value == 1


def test_first_matching_handler_only_second_arm_unreachable():
    """Positive twin: narrower arm first — leaf handler alone returns 1."""
    v = _val(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "def A(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except LeafFault:\n"
        "        return 1\n"
        "    except RootFault:\n"
        "        return 2\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].value == 1


def test_first_match_only_does_not_sequence_later_arm_return():
    """Later arms are not sequenced after a match — second return is dead."""
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "def A(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except LeafFault:\n"
        "        return 1\n"
        "    except RootFault:\n"
        "        return 99\n"
        "    return z\n"
    )
    assert not isinstance(out, Incomplete)
    v = out.value
    assert _incompletes(v) == []
    assert v.post().args[1].value == 1


# ---------------------------------------------------------------------------
# except-as: routed effect slot (not reconstructed E())
# ---------------------------------------------------------------------------


def test_as_binds_the_routed_effect_slot_not_a_reconstruction():
    """``as error`` projects the matched Halted raise via the handler slot.

    Post cites ``python:effect_slot``; origin links to the raise occurrence.
    No fabricated E() reconstruction.
    """
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as error:\n"
        "        return error\n"
    )
    assert _incompletes(v) == []
    post = v.post()
    assert post.args[1].name == "python:effect_slot"
    origins = [
        inv
        for inv in v.invs()
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_origin"
    ]
    assert origins, "as must link the slot to the routed raise occurrence"
    assert origins[0].args[1].name == "python:raise_effect_occurrence"
    # No type-derived identity reconstruction.
    assert not any(
        inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_identity"
        for inv in v.invs()
    )


# ---------------------------------------------------------------------------
# else: never after a halt, even if handled
# ---------------------------------------------------------------------------


def test_else_never_runs_after_halt_even_when_handler_consumes():
    """Caught raise is still a body halt — else is only Completed fall-through."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        return 0\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_else_runs_only_on_completed_body_exit():
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    else:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


# ---------------------------------------------------------------------------
# finally on all seven exits
#
# The seven exits a try body (or its handler routing) can present to finally:
#   1. normal completion (fall-through)
#   2. return
#   3. uncaught raise
#   4. caught raise → handler completion
#   5. caught raise → handler raise
#   6. break
#   7. continue
# ---------------------------------------------------------------------------


def test_finally_on_exit_1_normal_completion():
    """(1) Body completes; inert finally restores the completion."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        x = z\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_on_exit_2_body_return():
    """(2) Body return rides through inert finally as the function exit."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        return z\n"
        "    finally:\n"
        "        y = 1\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_on_exit_3_uncaught_raise_restored():
    """(3) Unmatched halt survives inert finally (restore, not invent complete)."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_finally_on_exit_4_caught_handler_completion():
    """(4) Matching handler completes; inert finally keeps that completion."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_on_exit_5_handler_raise_through_finally():
    """(5) Handler's own raise is the outgoing halt after inert finally."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise KeyError\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "KeyError"


def test_finally_on_exit_6_break():
    """(6) Break through inert finally — loop alone consumes its owned halt."""
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
    assert v.post().args[1].value == 1


def test_finally_on_exit_7_continue():
    """(7) Continue through inert finally — matching loop routes its latch."""
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
    assert v.post().args[1].value == 1


# ---------------------------------------------------------------------------
# Bare re-raise: same effect occurrence, no reconstruction
# ---------------------------------------------------------------------------


def test_bare_reraise_preserves_the_same_effect_occurrence():
    """Bare ``raise`` re-emits the in-flight RaiseEffect — same occurrence."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, RaiseEffect)
    assert out.effect.exception_name == "ValueError"
    # Occurrence is the original raise site (line of ``raise ValueError``),
    # not a reconstructed site at the bare re-raise.
    assert out.effect.occurrence.endswith(":6:8")
    assert out.effect.exception_type_coordinate == _identity("ValueError")


def test_bare_reraise_is_not_a_reconstructed_raise_at_handler_site():
    """No invented new occurrence at the bare-raise line."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, RaiseEffect)
    # Bare re-raise is on a later line; occurrence must NOT be that line.
    assert not out.effect.occurrence.endswith(":8:8")
    assert not out.effect.occurrence.endswith(":8:9")


# ---------------------------------------------------------------------------
# No invented fall-through
# ---------------------------------------------------------------------------


def test_uncaught_raise_does_not_invent_fallthrough_completion():
    """Mismatch arm leaves the halt — function body after try does not complete."""
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


def test_handler_halt_does_not_invent_post_try_fallthrough():
    """Handler raise is the exit; no fabricated completion after the try."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise RuntimeError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "RuntimeError"


def test_handler_raise_carries_the_handled_occurrence_as_context():
    """An explicit handler raise authenticates Python's chaining edge."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(
        "def A():\n"
        "    try:\n"
        "        raise ImportError('inner')\n"
        "    except ImportError:\n"
        "        raise ValueError('outer')\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, RaiseEffect)
    assert out.effect.exception_name == "ValueError"
    assert isinstance(out.effect.context_effect, RaiseEffect)
    assert out.effect.context_effect.exception_name == "ImportError"
    assert out.effect.context_effect.occurrence.endswith(":6:8")


# ---------------------------------------------------------------------------
# except* separately loud (ordinary try path ≠ except*)
# ---------------------------------------------------------------------------


def test_except_star_is_separately_loud_on_ordinary_raise():
    """except* refuses ordinary RaiseEffect — distinct router, stays loud."""
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except* ValueError:\n"
            "        pass\n"
            "    return z\n"
        ).sugar().desugar()


def test_ordinary_except_does_not_absorb_grouped_raise_silently():
    """Ordinary ``except ValueError`` never consumes ``raise ExceptionGroup``.

    The halt must survive AND must not have been rewritten into the arm's
    ``ValueError`` -- absorbing it silently is the failure this pins.
    """
    from sugar_lift_py_tests.outcome import Incomplete

    outcome = _out(
        "def A():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError()])\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    assert isinstance(outcome, Incomplete)
    # Not absorbed, and NOT rewritten into the arm's ordinary ValueError:
    # the grouped effect stays grouped, which is what keeps except* separate.
    assert isinstance(outcome.effect, GroupedRaiseEffect)
    assert getattr(outcome.effect, "exception_name", None) != "ValueError"


# ---------------------------------------------------------------------------
# finally: lines 5 and 6 of the six-line law.
#
# The twins above all use an INERT finally, which only exercises line 5
# ("finally completes -> preserve incoming exit").  Line 6 ("finally
# terminates -> override incoming exit") has two faces -- a return in the
# cleanup and a raise in the cleanup -- and each must beat BOTH incoming
# edges.  These are the ``cleanup_restores`` / cleanup-halt arms of the
# shared ``ExitSet.and_finally``.
# ---------------------------------------------------------------------------


_HALT_THEN_RETURN_IN_FINALLY = (
    "def A(z):\n"
    "    try:\n"
    "        raise ValueError\n"
    "    finally:\n"
    "        return z\n"
)


def test_finally_return_overrides_an_incoming_halt():
    """(line 6) ``return`` in finally supersedes the body's uncaught raise."""
    v = _val(_HALT_THEN_RETURN_IN_FINALLY)
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_return_override_bites_when_cleanup_is_read_as_restoring():
    """Bite for the twin above.

    ``TrySugar`` tells ``and_finally`` which cleanup completions are terminal
    via ``cleanup_restores``.  Force that predicate to the always-restores
    default -- the shape ``and_finally`` uses when a caller does NOT model
    return-in-finally -- and the incoming ValueError halt comes back.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    real = ExitSet.and_finally

    def always_restores(self, cleanup, *, cleanup_restores=None):
        return real(self, cleanup, cleanup_restores=lambda _v: True)

    ExitSet.and_finally = always_restores
    try:
        out = _out(_HALT_THEN_RETURN_IN_FINALLY)
    finally:
        ExitSet.and_finally = real

    from sugar_lift_py_tests.outcome import Incomplete

    assert isinstance(
        out, Incomplete
    ), "perturbation must resurrect the overridden halt"
    assert out.effect.exception_name == "ValueError"


def test_finally_raise_overrides_an_incoming_halt():
    """(line 6) Cleanup halt supersedes the body halt -- KeyError, not ValueError."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    out = _out(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    finally:\n"
        "        raise KeyError\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, RaiseEffect)
    assert out.effect.exception_name == "KeyError"


def test_finally_raise_overrides_an_incoming_completion():
    """(line 6) Cleanup halt also beats a COMPLETED incoming edge.

    The completed edge is the one the algebra had no contract parameter for
    until the completed-edge seam landed; a finally that raises must halt a
    body that finished normally, and must not invent a post-try fall-through.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        pass\n"
        "    finally:\n"
        "        raise KeyError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "KeyError"


# ---------------------------------------------------------------------------
# Structural: Try reaches the SHARED routing, it is not a third control model.
#
# Behavioral twins cannot tell "rode the shared algebra" from "hand-rolled a
# private fold that happens to agree".  This pair separates them the way the
# completed-edge seam twin did: spy the shared call, then swap in a
# behavior-identical private fold and show that ONLY the routing law goes red.
# ---------------------------------------------------------------------------


_FINALLY_OVER_A_PARTITION = (
    "def A(z, flag):\n"
    "    try:\n"
    "        if flag:\n"
    "            raise ValueError\n"
    "    except KeyError:\n"
    "        pass\n"
    "    finally:\n"
    "        y = 1\n"
    "    return z\n"
)


def _spy_and_finally():
    """Install a counting wrapper on the shared ``ExitSet.and_finally``."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    real = ExitSet.and_finally
    seen = []

    def spy(self, cleanup, **kwargs):
        seen.append(self)
        return real(self, cleanup, **kwargs)

    ExitSet.and_finally = spy
    return seen, real


def test_try_finally_routes_through_the_shared_exitset_and_finally():
    """``finally`` is the shared ``ExitSet.and_finally``, consulted once.

    It is handed the post-handler-routing ExitSet -- both edges of the body
    partition -- rather than a pre-decided single face.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    seen, real = _spy_and_finally()
    try:
        v = _val(_FINALLY_OVER_A_PARTITION)
    finally:
        ExitSet.and_finally = real

    assert len(seen) == 1, "finally must consult the shared fold exactly once"
    incoming = seen[0]
    kinds = {type(exit_).__name__ for exit_ in incoming.exits}
    assert kinds == {"Completed", "Halted"}, (
        "the shared fold must receive BOTH edges of the body partition, " f"got {kinds}"
    )
    assert any(
        isinstance(e, Halted) and e.effect.exception_name == "ValueError"
        for e in incoming.exits
    )
    assert any(isinstance(e, Completed) for e in incoming.exits)
    assert _incompletes(v), "the unmatched ValueError still rides out"


def test_shared_fold_spy_bites_on_a_behavior_identical_private_fold():
    """The bite: a private fold that agrees on every observable.

    ``TrySugar.desugar`` is replaced with a copy whose only difference is that
    it folds the cleanup through a module-private function instead of the
    shared ``ExitSet.and_finally``.  Behaviour is byte-identical -- every
    behavioural twin above stays green -- and ONLY the routing law goes red,
    which is what makes that law load-bearing rather than decorative.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.try_sugar import TrySugar

    honest = _val(_FINALLY_OVER_A_PARTITION)
    honest_reds = [e.effect.exception_name for e in _incompletes(honest)]

    real_and_finally = ExitSet.and_finally

    def _private_fold(exits, cleanup, *, cleanup_restores=None):
        # Deliberately NOT ExitSet.and_finally: same law, private door.
        return real_and_finally(exits, cleanup, cleanup_restores=cleanup_restores)

    real_desugar = TrySugar.desugar

    def desugar_via_private_fold(self, ctx=None):
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.sugar.try_sugar import _route_handlers_over_exits

        body_es = promote_raise_halts(reduce_block_to_exitset(self.body, ctx))
        pre_finally = _route_handlers_over_exits(
            body_es, self.handlers, self.orelse, site=self.site, ctx=ctx
        )
        if not self.finalbody:
            return exitset_to_outcome(pre_finally)
        cleanup_es = reduce_block_to_exitset(self.finalbody, ctx)

        def _restores(value):
            if isinstance(value, _ReducedBlock):
                if not value.can_fall_through:
                    return False
                return not any(isinstance(e, ReturnValue) for e in value.entries)
            return True

        return exitset_to_outcome(
            _private_fold(pre_finally, lambda: cleanup_es, cleanup_restores=_restores)
        )

    TrySugar.desugar = desugar_via_private_fold
    seen, real = _spy_and_finally()
    try:
        perturbed = _val(_FINALLY_OVER_A_PARTITION)
    finally:
        ExitSet.and_finally = real
        TrySugar.desugar = real_desugar

    # Behaviour is identical: no behavioural twin can see the private door.
    assert [e.effect.exception_name for e in _incompletes(perturbed)] == honest_reds
    # Only the routing law sees it.
    assert seen == [], "the private fold must be invisible to the shared call"


# ---------------------------------------------------------------------------
# Same instrument, two spellings: Try is not a second door onto the algebra.
#
# This is the shape that proved Assign unpack was not a second door -- read a
# ``try`` and its equivalent plain spelling through the SAME reducer and
# assert the arm structure is identical.
# ---------------------------------------------------------------------------


def _find_try(sugar):
    from sugar_lift_py_tests.sugar.try_sugar import TrySugar

    if isinstance(sugar, TrySugar):
        return sugar
    for field_name in getattr(sugar, "__dataclass_fields__", {}):
        value = getattr(sugar, field_name)
        for item in value if isinstance(value, tuple) else (value,):
            if hasattr(item, "__dataclass_fields__"):
                found = _find_try(item)
                if found is not None:
                    return found
    return None


def _guard_shape(guard):
    """Structural signature of a guard, blind to per-file CIDs."""
    kind = getattr(guard, "kind", None) or getattr(guard, "name", None)
    operands = getattr(guard, "operands", None)
    if operands is None:
        operands = getattr(guard, "args", ())
    return (type(guard).__name__, kind, tuple(_guard_shape(o) for o in operands))


def _arm_shape(exits):
    """Halted/Completed partition + guard structure + effect identity."""
    from sugar_lift_py_tests.outcome.exit_set import Completed

    shape = []
    for exit_ in exits.normalize().exits:
        if isinstance(exit_, Completed):
            shape.append(
                (
                    "Completed",
                    _guard_shape(exit_.guard),
                    getattr(exit_.value, "can_fall_through", None),
                )
            )
        else:
            shape.append(
                ("Halted", _guard_shape(exit_.guard), exit_.effect.exception_name)
            )
    return tuple(shape)


def _routed(src):
    """Body -> promote -> handler routing, through the shared reducer."""
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.try_sugar import _route_handlers_over_exits

    node = _find_try(_fn(src).sugar())
    assert node is not None
    body_es = promote_raise_halts(reduce_block_to_exitset(node.body, None))
    return (
        node,
        body_es,
        _route_handlers_over_exits(
            body_es, node.handlers, node.orelse, site=node.site, ctx=None
        ),
    )


_NON_MATCHING_ARM = (
    "def A(z, flag):\n"
    "    try:\n"
    "        if flag:\n"
    "            raise ValueError\n"
    "    except KeyError:\n"
    "        pass\n"
    "    return z\n"
)

_NO_ARM_AT_ALL = (
    "def A(z, flag):\n"
    "    try:\n"
    "        if flag:\n"
    "            raise ValueError\n"
    "    finally:\n"
    "        pass\n"
    "    return z\n"
)


def test_unmatched_try_and_its_equivalent_spelling_share_arm_structure():
    """A handler that cannot match leaves the body partition untouched.

    Same instrument, two spellings: routing a two-edge body through an arm
    that cannot match yields exactly the arm structure the bare body has.
    Try adds no arms, drops no arms, and re-guards nothing.
    """
    _node, _body, routed = _routed(_NON_MATCHING_ARM)
    _node2, bare, _routed2 = _routed(_NO_ARM_AT_ALL)

    assert _arm_shape(routed) == _arm_shape(bare)
    # And it is a genuine two-edge partition, not a degenerate single arm.
    assert len(routed.normalize().exits) == 2
    assert {kind for kind, _g, _e in _arm_shape(routed)} == {"Halted", "Completed"}


def test_matched_handler_routing_equals_the_handler_body_arm_structure():
    """A matched halt is REPLACED by the handler body's own arms.

    The routed result must equal what the handler body reduces to on its own
    through the same reducer -- no residual body arm, no invented
    fall-through, no second sequencing model.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    node, _body, routed = _routed(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return z\n"
    )
    handler_alone = reduce_block_to_exitset(node.handlers[0][1], None)
    assert _arm_shape(routed) == _arm_shape(handler_alone)


def test_equivalence_twin_bites_when_the_unmatched_arm_is_absorbed():
    """Bite for both twins above.

    Make every handler match (the classic 'absorb anything' defect).  The
    unmatched spelling then stops agreeing with its bare equivalent, and the
    two-edge partition collapses -- exactly the red these twins exist to give.
    """
    from sugar_lift_py_tests.sugar import try_sugar

    real = try_sugar._effect_matches
    try_sugar._effect_matches = lambda effect, matcher, ctx=None: True
    try:
        _node, _body, routed = _routed(_NON_MATCHING_ARM)
    finally:
        try_sugar._effect_matches = real

    _node2, bare, _r2 = _routed(_NO_ARM_AT_ALL)
    assert _arm_shape(routed) != _arm_shape(bare)
    assert not any(kind == "Halted" for kind, _g, _e in _arm_shape(routed))


# ---------------------------------------------------------------------------
# Source order / first match: bite by reversing the arms at the router.
# ---------------------------------------------------------------------------


_TWO_ARM_MRO = (
    "class RootFault(Exception):\n"
    "    pass\n"
    "class LeafFault(RootFault):\n"
    "    pass\n"
    "def A(z):\n"
    "    try:\n"
    "        raise LeafFault\n"
    "    except RootFault:\n"
    "        return 1\n"
    "    except LeafFault:\n"
    "        return 2\n"
    "    return z\n"
)


def test_first_match_is_source_order_and_bites_when_the_arms_are_reversed():
    """Both faces of the discriminator, through the shared router.

    Both arms match the raised ``LeafFault`` (it is a subclass of
    ``RootFault``), so the ONLY thing choosing between ``return 1`` and
    ``return 2`` is source order.  Feeding the router the reversed arm tuple
    must select the other body -- if it did not, the source-order twin above
    would be passing for a reason unrelated to its law.
    """
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.try_sugar import (
        _effect_matches,
        _route_handlers_over_exits,
    )

    node = _find_try(_fn(_TWO_ARM_MRO).sugar())
    body_es = promote_raise_halts(reduce_block_to_exitset(node.body, None))
    halted = [e for e in body_es.exits if type(e).__name__ == "Halted"]
    assert len(halted) == 1

    # Precondition of the discriminator: BOTH arms genuinely match.
    matchers = [m for m, _b, _s in node.handlers]
    assert all(
        _effect_matches(halted[0].effect, m, None) for m in matchers
    ), "both arms must match, else source order is not what is being tested"

    forward = _route_handlers_over_exits(
        body_es, node.handlers, node.orelse, site=node.site, ctx=None
    )
    reversed_ = _route_handlers_over_exits(
        body_es, tuple(reversed(node.handlers)), node.orelse, site=node.site, ctx=None
    )

    first_arm = reduce_block_to_exitset(node.handlers[0][1], None)
    second_arm = reduce_block_to_exitset(node.handlers[1][1], None)

    assert _arm_shape(forward) == _arm_shape(first_arm)
    assert _arm_shape(reversed_) == _arm_shape(second_arm)
    # And the two arm bodies are actually distinguishable to the instrument.
    assert _returned_constants(forward) == (1,)
    assert _returned_constants(reversed_) == (2,)


def _returned_constants(exits):
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome.exit_set import Completed

    out = []
    for exit_ in exits.normalize().exits:
        if not isinstance(exit_, Completed):
            continue
        for entry in getattr(exit_.value, "entries", ()):
            if isinstance(entry, ReturnValue):
                value = getattr(entry.value, "value", None)
                term = getattr(getattr(entry.value, "term", None), "value", None)
                if value is not None:
                    out.append(value)
                elif term is not None:
                    out.append(term)
    return tuple(out)


# ---------------------------------------------------------------------------
# else: a two-sided discriminator that needs no monkeypatch.
#
# ``else`` runs ONLY over completed edges.  So adding an ``else`` block must
# change the routed arms for a body that can complete, and must change
# NOTHING for a body that only halts.  A leak onto the halted edge fails the
# second half; an ``else`` that never runs at all fails the first.
# ---------------------------------------------------------------------------


_ALL_HALT_NO_ELSE = (
    "def A(z):\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        pass\n"
    "    return z\n"
)

_ALL_HALT_WITH_ELSE = (
    "def A(z):\n"
    "    try:\n"
    "        raise ValueError\n"
    "    except ValueError:\n"
    "        pass\n"
    "    else:\n"
    "        return 7\n"
    "    return z\n"
)

_CAN_COMPLETE_NO_ELSE = (
    "def A(z):\n"
    "    try:\n"
    "        pass\n"
    "    except ValueError:\n"
    "        pass\n"
    "    return z\n"
)

_CAN_COMPLETE_WITH_ELSE = (
    "def A(z):\n"
    "    try:\n"
    "        pass\n"
    "    except ValueError:\n"
    "        pass\n"
    "    else:\n"
    "        return 7\n"
    "    return z\n"
)


def test_else_changes_nothing_on_a_body_that_only_halts():
    """Negative face: the halted edge never sees ``else``.

    The body raises unconditionally and the handler consumes it, so the try
    presents no completed edge.  Attaching an ``else`` must be a no-op on the
    routed arms -- byte-identical structure AND no ``return 7``.
    """
    _n1, _b1, without = _routed(_ALL_HALT_NO_ELSE)
    _n2, _b2, with_else = _routed(_ALL_HALT_WITH_ELSE)
    assert _arm_shape(without) == _arm_shape(with_else)
    assert 7 not in _returned_constants(with_else)


def test_else_does_change_the_routed_arms_on_a_body_that_completes():
    """Positive face: the completed edge DOES see ``else``.

    Same discriminator, other arm.  Without this the twin above would pass
    for an ``else`` that is simply never wired up.
    """
    _n1, _b1, without = _routed(_CAN_COMPLETE_NO_ELSE)
    _n2, _b2, with_else = _routed(_CAN_COMPLETE_WITH_ELSE)
    assert _returned_constants(without) == ()
    assert 7 in _returned_constants(with_else)
