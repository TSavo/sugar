from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.outcome import Incomplete


def test_nonlocal_mutation_is_a_named_shared_scope_effect() -> None:
    result = compose_block("    nonlocal shared\n    shared = 2\n    return shared\n")

    effect = next(row for row in result.statements if isinstance(row, Incomplete))
    assert type(effect.effect).__name__ == "NonlocalMutationRuntimeEffect"
    assert "shared" in effect.reason
