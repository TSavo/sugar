"""except-as target cleanup — binding deleted after handler exits.

Python clears the exception target at the end of the except clause. After the
handler exits (Completed fall-through, Returned, or Halted), the name is unbound
on every continuing edge; unrelated temporal bindings survive.

Laws:

- post-try / finally / else read of ``as e`` → NameError (binding deleted)
- inside handler: return e / raise from e observe the routed effect
- unrelated pre-try and in-handler assignments survive after cleanup

Does not touch ExitSet algebra, carrier, or assertion/resource routing.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.effect_coordinate import ObservedEffectValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "except_as_cleanup.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return list(tree.functions())[-1].sugar().desugar()


def _name_error(outcome, *, name: str = "e"):
    """Project a NameError for ``name`` from Incomplete or ExitSet halt."""
    if isinstance(outcome, Incomplete):
        effect = outcome.effect
        assert type(effect).__name__ == "NameErrorEffect", type(effect)
        assert getattr(effect, "name", None) == name
        return effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        effect = halted[0].effect
        assert type(effect).__name__ == "NameErrorEffect", type(effect)
        assert getattr(effect, "name", None) == name
        return effect
    raise AssertionError(f"expected NameError halt, got {type(outcome)}: {outcome}")


def _return_value(outcome):
    assert isinstance(outcome, Complete), outcome
    returns = [
        s for s in outcome.value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, outcome.value.record.statements
    return returns[0].value


# ---------------------------------------------------------------------------
# Binding deleted after handler exits (Completed / after-try / finally / else)
# ---------------------------------------------------------------------------


def test_post_try_read_of_except_as_target_is_name_error():
    """After except falls through, ``e`` is unbound on the continuing edge."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        pass\n"
        "    return e\n",
        name="post_try_e.py",
    )
    _name_error(outcome, name="e")


def test_finally_read_of_except_as_target_is_name_error():
    """``as e`` is cleared before finally — not visible on the cleanup edge."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        pass\n"
        "    finally:\n"
        "        return e\n",
        name="finally_e.py",
    )
    _name_error(outcome, name="e")


def test_else_read_of_except_as_target_is_name_error():
    """else runs only on body fall-through — never has the except-as binding."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except ValueError as e:\n"
        "        pass\n"
        "    else:\n"
        "        return e\n",
        name="else_e.py",
    )
    _name_error(outcome, name="e")


# ---------------------------------------------------------------------------
# Binding live on handler Completed / Returned / Halted faces
# ---------------------------------------------------------------------------


def test_handler_return_observes_routed_effect():
    """Returned face: ``return e`` projects the authenticated routed RaiseEffect."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        return e\n",
        name="handler_return_e.py",
    )
    value = _return_value(outcome)
    assert isinstance(value, ObservedEffectValue), type(value)
    assert isinstance(value.effect, RaiseEffect)
    assert value.effect.exception_name == "ValueError"


def test_handler_halt_from_e_uses_routed_cause():
    """Halted face: ``raise Outer from e`` keeps e as authenticated cause."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from e\n",
        name="handler_halt_from_e.py",
    )
    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "RuntimeError"
    assert isinstance(outcome.effect.cause_value, ObservedEffectValue)
    assert outcome.effect.cause_value.effect.exception_name == "ValueError"


# ---------------------------------------------------------------------------
# Unrelated temporal bindings survive cleanup
# ---------------------------------------------------------------------------


def test_pre_try_binding_survives_except_as_cleanup():
    """``y`` bound before try survives after except-as cleanup."""
    outcome = _desugar(
        "def f():\n"
        "    y = 7\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        pass\n"
        "    return y\n",
        name="pre_try_y.py",
    )
    value = _return_value(outcome)
    assert value.value == 7


def test_handler_body_binding_survives_except_as_cleanup():
    """``y`` assigned inside the handler survives after ``e`` is cleared."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        y = 3\n"
        "    return y\n",
        name="handler_y.py",
    )
    value = _return_value(outcome)
    assert value.value == 3


def test_post_try_e_deleted_while_handler_y_survives():
    """Same try: e deleted after handler, y from handler still readable."""
    deleted = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        y = 1\n"
        "    return e\n",
        name="delete_e.py",
    )
    _name_error(deleted, name="e")
    survived = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        y = 1\n"
        "    return y\n",
        name="survive_y.py",
    )
    assert _return_value(survived).value == 1
