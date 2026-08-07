"""An undecidable handler match is RETAINED, never decided, never loud.

`matches_raise_effect` is the one matcher shared by Try and With, so every
assertion boundary depends on its codomain being honest. Its message half was
closed to three outcomes once already, after a `bool` codomain let
`with hold(ValueError, match="boom")` restore a halt *as if* the pattern had
been checked -- a fabricated fact in the emitted FOL. Its identity half was
still two-valued plus a panic:

    def f(exc):
        try:
            raise exc
        except ValueError:
            return 1

Nobody can decide at lift whether the runtime type of the formal `exc` is a
`ValueError`. That is not a construction gap -- both operands produce perfectly
good terms -- and it is emphatically not `False`. It is a real predicate this
compiler cannot settle, so it leaves as `adt.is_python_type(exc, ValueError)`,
the reserved tester atom the floor already emits for exactly this question, and
the router partitions the incoming exit by it.

Both faces are pinned here, because each alone is a distinct lie:

- **Never admitted.** The raise must still be on the wall. A router that
  routed the retained arm into the handler and stopped would have silently
  claimed the exception was caught.
- **Never dropped.** The obligation must appear in the emitted FOL. A router
  that propagated the halt and forgot the predicate would have silently
  claimed the handler is unreachable.

And the decided arms must stay decided: an obligation emitted where the
compiler *could* answer is its own fabrication, so the ground cases assert the
tester atom does not appear at all.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.outcome import Incomplete, outcome_to_exitset
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

TESTER_ATOM = "adt.is_python_type"


def _universe(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of

    source_file = SourceFile(
        (source, "/tmp/retained_identity.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return list(source_file.functions())[-1].sugar().desugar()


def _residual_raises(source: str) -> tuple[str, ...]:
    """Every raise that survived the `try` -- the effects still on the wall."""
    exit_set = outcome_to_exitset(_universe(source))
    names: list[str] = []
    seen: set[int] = set()

    def walk(value: object) -> None:
        if value is None or isinstance(value, (str, int, bool, float, bytes)):
            return
        key = id(value)
        if key in seen:
            return
        seen.add(key)
        if isinstance(value, Incomplete) and isinstance(value.effect, RaiseEffect):
            names.append(value.effect.exception_name)
        effect = getattr(value, "effect", None)
        if isinstance(effect, RaiseEffect):
            names.append(effect.exception_name)
        for attribute in ("statements", "record", "value", "exits", "entries"):
            child = getattr(value, attribute, None)
            if isinstance(child, tuple):
                for item in child:
                    walk(item)
            else:
                walk(child)

    for face in exit_set.exits:
        walk(face)
    return tuple(sorted(set(names)))


def _tester_atom_count(source: str) -> int:
    """How many times the reserved type-tester atom reaches the emitted FOL."""
    return repr(_universe(source)).count(TESTER_ATOM)


_FORMAL_ONE_ARM = (
    "def f(exc):\n"
    "    try:\n"
    "        raise exc\n"
    "    except ValueError:\n"
    "        return 1\n"
    "    return 3\n"
)

_FORMAL_TWO_ARMS = (
    "def f(exc):\n"
    "    try:\n"
    "        raise exc\n"
    "    except ValueError:\n"
    "        return 1\n"
    "    except KeyError:\n"
    "        return 2\n"
    "    return 3\n"
)


# --- the undecidable arm: retained, both faces alive -------------------------


def test_formal_raise_is_not_swallowed_by_a_typed_handler():
    # NEVER ADMITTED: the handler did not prove it catches this, so the halt
    # stands. `exc` on the wall is the whole point -- a router that consumed it
    # would have decided a runtime type question at lift.
    assert _residual_raises(_FORMAL_ONE_ARM) == ("exc",)


def test_formal_raise_emits_the_handler_obligation():
    # NEVER DROPPED: the handler face is real and reachable, and the predicate
    # under which it is reachable is stated rather than assumed away.
    assert _tester_atom_count(_FORMAL_ONE_ARM) > 0


def test_every_arm_after_a_retained_arm_still_gets_its_own_obligation():
    # A retained arm narrows the residual to its complement instead of ending
    # the walk, so a later arm is considered under `not(first)` and states its
    # own predicate. Collapsing the walk at the first retention would leave the
    # second handler unreachable by silence.
    assert _tester_atom_count(_FORMAL_TWO_ARMS) > _tester_atom_count(_FORMAL_ONE_ARM)
    assert _residual_raises(_FORMAL_TWO_ARMS) == ("exc",)


def test_bare_except_over_a_formal_raise_is_decided_not_retained():
    # A bare `except` catches every raise by the language's own rule -- there is
    # no type question, so there is no obligation to state and nothing survives.
    source = (
        "def f(exc):\n"
        "    try:\n"
        "        raise exc\n"
        "    except:\n"
        "        return 1\n"
        "    return 3\n"
    )
    assert _residual_raises(source) == ()
    assert _tester_atom_count(source) == 0


# --- the decided arms must stay decided --------------------------------------


def test_authenticated_exact_match_states_no_obligation():
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('b')\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    return 3\n"
    )
    assert _residual_raises(source) == ()
    assert _tester_atom_count(source) == 0


def test_authenticated_miss_stays_red_and_states_no_obligation():
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('b')\n"
        "    except KeyError:\n"
        "        return 1\n"
        "    return 3\n"
    )
    assert _residual_raises(source) == ("ValueError",)
    assert _tester_atom_count(source) == 0


def test_authenticated_ancestor_match_states_no_obligation():
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('b')\n"
        "    except Exception:\n"
        "        return 1\n"
        "    return 3\n"
    )
    assert _residual_raises(source) == ()
    assert _tester_atom_count(source) == 0
