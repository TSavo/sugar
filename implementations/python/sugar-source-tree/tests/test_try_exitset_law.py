"""STAGED law twins for Try/ExitSet. DO NOT treat green as merge-ready.

Merge waits on the post-V2 / post-Merkle census gate (PR #6242).

Six-line foundational path::

    body
      → guarded ExitSet
      → handler routing over Halted
      → finally over every exit

Pinned twins (this module):

- handlers in source order
- first match only
- ``as`` uses the routed effect slot
- ``else`` never after a halt, even if handled
- ``finally`` on all seven exits
- bare re-raise preserves the same effect occurrence
- no reconstruction of the raised effect
- no invented fall-through
- ``except*`` stays separately loud (ordinary try ≠ except*)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_source_tree.panic import SugarNotWritten
from with_resolution_fixture import source_file_with_preconstruction


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
    assert out.effect.exception_type_coordinate is not None


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
    """Ordinary except never silently consumes a grouped raise."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    outcome = _out(
        "def A():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError()])\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, (GroupedRaiseEffect, RaiseEffect))


def test_try_sugar_module_still_names_the_six_line_law():
    """Production module documents the foundational ExitSet path."""
    path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "try_sugar.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "guarded ExitSet" in text
    assert "_route_handlers_over_exits" in text
    assert "and_finally" in text or "finally" in text
