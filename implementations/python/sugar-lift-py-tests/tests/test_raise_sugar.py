"""RaiseSugar: a `raise` statement IS an effect. It desugars to `Incomplete(RaiseEffect)`
with no reduction and no detection -- the sugar simply is the Incomplete. The block
reducing it bubbles the Incomplete upward and does no work past it (the raise transfers
control, so every statement after it is unreachable).
"""

from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar


def _block(src: str):
    return compose_block(src, {})


def test_raise_desugars_directly_to_an_incomplete_effect():
    assert isinstance(RaiseSugar().desugar(), Incomplete)


def test_raise_halts_the_block_and_the_line_after_it_is_never_collected():
    # `raise ...; return 1` -- the return is unreachable, so the block is Incomplete and
    # NEVER yields a BlockValue with `return 1` in it.
    halted = _block('    raise ValueError("boom")\n    return 1\n')
    assert isinstance(halted, Incomplete)


def test_a_block_with_only_a_raise_is_incomplete():
    assert isinstance(_block('    raise RuntimeError("x")\n'), Incomplete)
