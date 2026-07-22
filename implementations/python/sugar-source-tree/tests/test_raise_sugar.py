"""`raise` sugar on the AST tree: the halt arm, proven through the node.

A raise never states a fact and never returns a value -- it exits. So its
`.sugar().desugar()` is an `Incomplete(RaiseEffect)`, the halt arm of
`match(Sugar) { Some => cite_or_effect, None => panic }`, not a `Complete`
floor value. The exception child builds normally and rides on the effect; its
structural name is routing provenance only. `raise X from Y` is loud until
cause-carrying is written -- a MISSING never becomes a silent success.
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
    # raise E, raise E(...), raise mod.E, raise mod.E(...) all name E / mod.E,
    # independently of the normally built child carried by the exit.
    assert _effect("def A():\n    raise ValueError\n").exception_name == "ValueError"
    assert _effect("def A():\n    raise ValueError('x')\n").exception_name == "ValueError"
    assert _effect("def A():\n    raise os.error\n").exception_name == "os.error"
    assert _effect("def A():\n    raise a.b.E(1)\n").exception_name == "a.b.E"


def test_bare_reraise_is_still_a_real_halt_with_no_name():
    # def A(): raise -- a re-raise: exc is None, so the name is None, but the
    # halt is no less real. The effect is the fact; the name is only its label.
    eff = _effect("def A():\n    raise\n")
    assert eff.exception_name is None
    assert "unknown exception" in eff.reason


def test_the_lift_discriminates_the_exception_name():
    # The name is not guessed: a raise of KeyError does NOT read as ValueError.
    # This is the truthful/lying discrimination the witness pair encodes.
    assert _effect("def A():\n    raise ValueError\n").exception_name == "ValueError"
    assert _effect("def A():\n    raise KeyError\n").exception_name == "KeyError"
    assert (
        _effect("def A():\n    raise ValueError\n").exception_name
        != _effect("def A():\n    raise KeyError\n").exception_name
    )


def test_raise_from_is_loud_until_cause_carrying_is_written():
    # def A(): raise X from Y -- the cause is chaining provenance we do not carry
    # yet. Rather than silently drop it, the sugar is LOUD: SugarNotWritten.
    with pytest.raises(SugarNotWritten):
        _raise("def A():\n    raise ValueError from KeyError\n").sugar()


if __name__ == "__main__":
    test_raise_is_the_halt_arm_not_a_value()
    test_exception_name_is_read_structurally()
    test_bare_reraise_is_still_a_real_halt_with_no_name()
    test_the_lift_discriminates_the_exception_name()
    test_raise_from_is_loud_until_cause_carrying_is_written()
    print("ok: raise -> Incomplete(RaiseEffect); name structural; from is loud")
