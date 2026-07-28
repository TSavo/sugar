"""finally swallows control — restore vs supersede laws.

Item-4 (implicit context vs from None + occurrence twins) is already covered
by ``test_exception_context_reraise.py`` (#6708). This instrument self-serves
the next live exception-lane law: **finally control-flow composition**.

Python ``try``/``finally``:

- cleanup fall-through **restores** the incoming exit (return / raise / break)
- cleanup terminal return **supersedes** the incoming exit (swallows raise)
- cleanup raise **supersedes** the incoming exit (return has no context;
  raise retains body raise as authenticated ``context_effect``)

Twins refuse: restored when supersede was required, and lost body context when
finally raise follows a body raise.

Does not touch ExitSet algebra, carrier, or assertion/resource routing.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "finally_control.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return list(tree.functions())[-1].sugar().desugar()


def _return_values(outcome) -> list:
    assert isinstance(outcome, Complete), outcome
    return [
        s.value.value if hasattr(s.value, "value") else s.value
        for s in outcome.value.record.statements
        if isinstance(s, ReturnValue)
    ]


def _halt_effect(outcome) -> RaiseEffect:
    if isinstance(outcome, Incomplete):
        assert isinstance(outcome.effect, RaiseEffect), type(outcome.effect)
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        assert isinstance(halted[0].effect, RaiseEffect), type(halted[0].effect)
        return halted[0].effect
    raise AssertionError(f"expected halt, got {type(outcome)}")


# ---------------------------------------------------------------------------
# Restore: inert finally preserves incoming control
# ---------------------------------------------------------------------------


def test_finally_pass_restores_try_return():
    """``return`` in try + fall-through finally → return survives."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        x = 0\n",
        name="restore_return.py",
    )
    assert _return_values(outcome) == [1]


def test_finally_pass_restores_try_raise():
    """``raise`` in try + fall-through finally → raise survives."""
    effect = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('body')\n"
            "    finally:\n"
            "        x = 0\n",
            name="restore_raise.py",
        )
    )
    assert effect.exception_name == "ValueError"


def test_finally_pass_restores_break():
    """``break`` in try + fall-through finally → break proceeds out of loop."""
    outcome = _desugar(
        "def f():\n"
        "    for i in [1, 2]:\n"
        "        try:\n"
        "            break\n"
        "        finally:\n"
        "            x = 1\n"
        "    return 3\n",
        name="restore_break.py",
    )
    assert _return_values(outcome) == [3]


# ---------------------------------------------------------------------------
# Supersede: terminal finally return swallows incoming control
# ---------------------------------------------------------------------------


def test_finally_return_supersedes_try_return():
    """``return`` in finally beats ``return`` in try."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    finally:\n"
        "        return 2\n",
        name="super_ret_ret.py",
    )
    assert _return_values(outcome) == [2]


def test_finally_return_swallows_try_raise():
    """``return`` in finally swallows body raise — no residual ValueError."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('body')\n"
        "    finally:\n"
        "        return 9\n",
        name="super_ret_raise.py",
    )
    assert isinstance(outcome, Complete), outcome
    assert _return_values(outcome) == [9]


def test_finally_return_supersedes_break():
    """``return`` in finally beats ``break`` — function returns from cleanup."""
    outcome = _desugar(
        "def f():\n"
        "    for i in [1, 2]:\n"
        "        try:\n"
        "            break\n"
        "        finally:\n"
        "            return 7\n"
        "    return 0\n",
        name="super_ret_break.py",
    )
    assert _return_values(outcome) == [7]


# ---------------------------------------------------------------------------
# Supersede: terminal finally raise
# ---------------------------------------------------------------------------


def test_finally_raise_supersedes_try_return_without_return_context():
    """``raise`` in finally beats ``return``; return is not exception context."""
    effect = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        return 1\n"
            "    finally:\n"
            "        raise RuntimeError('fin')\n",
            name="super_raise_ret.py",
        )
    )
    assert effect.exception_name == "RuntimeError"
    # No body exception to chain — return is not a RaiseEffect.
    assert effect.context_effect is None


def test_finally_raise_supersedes_try_raise_with_body_context():
    """``raise`` in finally beats body raise; body is authenticated context."""
    effect = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('body')\n"
            "    finally:\n"
            "        raise RuntimeError('fin')\n",
            name="super_raise_raise.py",
        )
    )
    assert effect.exception_name == "RuntimeError"
    assert isinstance(effect.context_effect, RaiseEffect)
    assert effect.context_effect.exception_name == "ValueError"
    assert effect.context_effect.occurrence != effect.occurrence
    assert effect.cause_value is None  # implicit context, not from-cause


# ---------------------------------------------------------------------------
# Twins — refuse restore-when-supersede and lost body context
# ---------------------------------------------------------------------------


def test_twin_finally_return_must_not_restore_body_raise():
    """Lying twin: if finally return restored the body raise, ValueError would win."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError('body')\n"
        "    finally:\n"
        "        return 9\n",
        name="twin_no_restore_raise.py",
    )
    assert isinstance(outcome, Complete), outcome
    assert not isinstance(outcome, Incomplete)
    assert _return_values(outcome) == [9]
    # Explicitly refuse residual raise as primary.
    if isinstance(outcome, Incomplete):
        raise AssertionError("body raise must not survive finally return")


def test_twin_finally_raise_after_body_raise_must_keep_context():
    """Lying twin: primary RuntimeError with no ValueError context is refused."""
    effect = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('body')\n"
            "    finally:\n"
            "        raise RuntimeError('fin')\n",
            name="twin_keep_context.py",
        )
    )
    assert effect.exception_name == "RuntimeError"
    assert effect.context_effect is not None, (
        "MISSING: finally raise after body raise must carry body as context_effect"
    )
    assert effect.context_effect.exception_name == "ValueError"
    # Refuse swapped primary/context.
    assert not (
        effect.exception_name == "ValueError"
        and effect.context_effect.exception_name == "RuntimeError"
    )
