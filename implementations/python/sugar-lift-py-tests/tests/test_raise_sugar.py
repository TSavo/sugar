"""RaiseSugar: a `raise` statement is Python control-flow data.

It desugars to a routeable `RaiseValue`, not an `Incomplete`, so `TrySugar` can
catch it. The block frontier still halts on that path: statements after the raise are
unreachable unless another guarded path falls through.
"""

from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, RaiseValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar


def _block(src: str):
    return compose_block(src, {})


def test_raise_desugars_directly_to_a_routeable_raise_exit():
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import default_catalog

    src = "def f():\n    raise ValueError('x')\n"
    mod = SourceFragment.from_source(src, "t.py").statements()[0]
    fn = [s for s in mod.statements() if s.observed == "FunctionDef"][0]
    # body block first stmt is raise
    block = fn.function_body_block()
    raise_site = block.statements()[0]
    sugar = RaiseSugar.new(
        raise_site, FactoryBuildContext(filename="t.py", catalog=default_catalog())
    )
    outcome = sugar.desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)


def test_raise_halts_the_block_and_the_line_after_it_is_never_collected():
    # `raise ...; return 1` -- the return is unreachable, so the block frontier carries
    # only the raise exit and NEVER yields a BlockValue with `return 1` in it.
    halted = _block('    raise ValueError("boom")\n    return 1\n')
    assert isinstance(halted, BlockValue)
    assert len(halted.statements) == 1
    assert isinstance(halted.statements[0], RaiseValue)


def test_a_block_with_only_a_raise_carries_a_raise_exit():
    block = _block('    raise RuntimeError("x")\n')

    assert isinstance(block, BlockValue)
    assert len(block.statements) == 1
    assert isinstance(block.statements[0], RaiseValue)


def test_caught_exception_reconstruction_is_a_routeable_dynamic_raise():
    caught = CallSiteValue(
        target_name="except",
        arg_values=(),
        parameters=(),
        term=ctor("py.except", [str_const("Exception")]),
        body=None,
    )
    block = compose_block(
        '    raise type(err)("new") from err\n',
        {"err": caught},
    )
    assert isinstance(block, BlockValue)

    dynamic = [
        statement
        for statement in block.statements
        if isinstance(statement, RaiseValue)
        and statement.effect.exception_type_coordinate is not None
    ]
    assert len(dynamic) == 1
    assert dynamic[0].effect.exception_name is None
    assert dynamic[0].cause is not None
