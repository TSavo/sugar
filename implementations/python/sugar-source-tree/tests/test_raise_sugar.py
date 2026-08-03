"""`raise` sugar on the AST tree: the halt arm, proven through the node.

A raise never states a fact and never returns a value -- it exits. So its
`.sugar().desugar()` is an `Incomplete(RaiseEffect)`, the halt arm of
`match(Sugar) { Some => cite_or_effect, None => panic }`, not a `Complete`
floor value. The exception child builds normally and rides on the effect; its
structural name is routing provenance only. Explicit causes are covered by the
binary raise contract tests; bare re-raise remains an active-context gap.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _raise(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    return next(n for n in fn.walk() if n.kind == "Raise")


def _effect(src: str):
    from sugar_lift_py_tests.outcome import Incomplete

    out = _raise(src).sugar().desugar()
    assert isinstance(out, Incomplete), f"raise must halt, got {type(out).__name__}"
    assert type(out.effect).__name__ == "RaiseEffect"
    return out.effect


def test_raise_is_the_halt_arm_not_a_value():
    # def A(): raise ValueError -- desugars to Incomplete(RaiseEffect), a typed
    # red halt, never a Complete floor value.
    eff = _effect("def A():\n    raise ValueError\n")
    assert eff.exception_name == "ValueError"
    assert "raise ValueError" in eff.reason


def test_exception_name_is_read_structurally():
    # Structural name is Raise construction, not desugar: raise E / E(...) /
    # mod.E / mod.E(...) label the halt. Opaque attribute desugar is a different
    # door (attribute floor); do not require it here.
    def name(src: str) -> str | None:
        return _raise(src).sugar().exception_name

    assert name("def A():\n    raise ValueError\n") == "ValueError"
    assert name("def A():\n    raise ValueError('x')\n") == "ValueError"
    assert name("def A():\n    raise os.error\n") == "os.error"
    assert name("def A():\n    raise a.b.E(1)\n") == "a.b.E"


def test_bare_reraise_stays_loud_until_active_exception_context_exists():
    with pytest.raises(SugarNotWritten):
        _raise("def A():\n    raise\n").sugar()


def test_the_lift_discriminates_the_exception_name():
    # The name is not guessed: a raise of KeyError does NOT read as ValueError.
    # This is the truthful/lying discrimination the witness pair encodes.
    assert _effect("def A():\n    raise ValueError\n").exception_name == "ValueError"
    assert _effect("def A():\n    raise KeyError\n").exception_name == "KeyError"
    assert (
        _effect("def A():\n    raise ValueError\n").exception_name
        != _effect("def A():\n    raise KeyError\n").exception_name
    )


def test_raise_from_carries_both_constructed_values():
    effect = _effect("def A():\n    raise ValueError from KeyError\n")
    assert effect.raised_value is not None
    assert effect.cause_value is not None


def test_authenticated_raise_constructs_raise_effect_not_nameerror():
    """Wiring law: RaiseSugar.desugar reaches AuthenticatedRaiseLocus + RaiseEffect.

    The exception-type identity door and RaiseEffect constructor already exist.
    Missing the locus import made every authenticated raise NameError at desugar
    — a wrong entrance, not missing sugar. Coordinate must be present.
    """
    from sugar_lift_py_tests.effect.authenticated_raise_locus import (
        AuthenticatedRaiseLocus,
    )
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    effect = _effect("def A():\n    raise ValueError\n")
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate is not None
    assert isinstance(effect.occurrence, AuthenticatedRaiseLocus)
    assert effect.exception_name == "ValueError"


def test_raise_call_form_carries_exception_type_coordinate():
    """``raise ValueError('x')`` constructs through the same Raise door."""
    effect = _effect("def A():\n    raise ValueError('x')\n")
    assert effect.exception_name == "ValueError"
    assert effect.exception_type_coordinate is not None


def test_local_exception_class_constructs_authenticated_raise_effect():
    """Source ClassDef exception types construct through the Raise door."""
    effect = _effect("class E(Exception):\n    pass\n\ndef A():\n    raise E\n")
    assert effect.exception_name == "E"
    assert effect.exception_type_coordinate is not None


def test_handler_reraise_resolves_in_flight_effect_not_isolated_desugar():
    """Bare re-raise is loud alone; through TrySugar the in-flight slot binds.

    Wrong entrance would desugar the bare Raise in isolation (no effect testimony).
    The real door is function/Try reduction, which bind_in_flight_effect owns.
    """
    from sugar_lift_py_tests.outcome import Incomplete

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(
            "def A():\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except ValueError:\n"
            "        raise\n"
        )
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    # Full body door — not an isolated Raise.desugar without handler context.
    outcome = fn.sugar().desugar()
    # Universe/block may collapse to ExitSet or Incomplete; extract raise effects.
    effects = []
    if isinstance(outcome, Incomplete):
        effects.append(outcome.effect)
    else:
        exits = getattr(outcome, "exits", None) or getattr(
            getattr(outcome, "value", None), "exits", ()
        )
        if exits is None:
            exits = ()
        for exit_ in exits:
            eff = getattr(exit_, "effect", None)
            if eff is not None:
                effects.append(eff)
    assert effects, f"expected a raise effect from handler re-raise, got {outcome!r}"
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    assert any(isinstance(e, RaiseEffect) for e in effects)
    named = next(e for e in effects if isinstance(e, RaiseEffect))
    assert named.exception_name == "ValueError"
    assert named.exception_type_coordinate is not None


if __name__ == "__main__":
    test_raise_is_the_halt_arm_not_a_value()
    test_exception_name_is_read_structurally()
    test_bare_reraise_stays_loud_until_active_exception_context_exists()
    test_the_lift_discriminates_the_exception_name()
    test_raise_from_carries_both_constructed_values()
    test_authenticated_raise_constructs_raise_effect_not_nameerror()
    test_raise_call_form_carries_exception_type_coordinate()
    test_local_exception_class_constructs_authenticated_raise_effect()
    test_handler_reraise_resolves_in_flight_effect_not_isolated_desugar()
    print("ok: raise -> Incomplete(RaiseEffect); explicit cause carried")
