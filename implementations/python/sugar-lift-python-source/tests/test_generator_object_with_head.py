"""An undecorated generator function at a With head raises TypeError, never manages.

``with g():`` where ``g`` is a plain generator function evaluates the call --
which returns a generator object and runs none of ``g``'s body -- and then the
``with`` statement raises ``TypeError``: a generator object has no
``__enter__``. Before this cut an imported undecorated generator was seated on
the generator-manager path (``GeneratorWithSugar``): its first ``yield`` was
taken as enter and the body ran, so ``f`` was claimed to return 7. The type and
text are the interpreter's own, observed by running it.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.generator_object_with_refusal import (
    observed_generator_object_with_refusal,
)
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.sugar.generator_with_sugar import (
    GeneratorObjectWithSugar,
    GeneratorWithSugar,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar

from test_contextmanager_generator_protocol import (
    _SUPPRESSES_VALUE_ERROR,
    _function_rows,
    _imported,
)

_UNDECORATED = "def cm():\n    try:\n        yield 1\n    except ValueError:\n        pass\n"


def _generator():
    yield  # pragma: no cover


def test_the_refusal_is_the_interpreters_own():
    refusal = observed_generator_object_with_refusal()
    with pytest.raises(Exception) as raised:
        with _generator():  # type: ignore[attr-defined]
            pass  # pragma: no cover
    assert refusal.exception_name == type(raised.value).__name__ == "TypeError"
    assert refusal.message == str(raised.value)


@pytest.mark.parametrize("contextlib_enrolled", (True, False))
@pytest.mark.parametrize(
    "body", ("pass", "raise ValueError('v')", "return 8"), ids=("pass", "raise", "return")
)
def test_an_imported_undecorated_generator_halts_with_type_error(
    tmp_path, contextlib_enrolled, body
):
    opened = _imported(
        tmp_path, _UNDECORATED, body, contextlib_enrolled=contextlib_enrolled
    )
    # The body never runs: no return 7, no ValueError, no return 8, and the
    # generator's own ``except ValueError`` never suppresses anything.
    assert _function_rows(*opened) == (GeneratorObjectWithSugar, [("halt", "TypeError")])


def _halt_effects(source_file):
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    effects = []
    for face in func.sugar().desugar().exits:
        if isinstance(face, Halted):
            effects.append(face.effect)
            continue
        for entry in getattr(getattr(face.value, "record", None), "statements", ()):
            if isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                effects.extend(halt.effect for halt in entry.halts())
    return effects


def test_the_halt_carries_the_observed_text(tmp_path):
    tree, _with_node = _imported(tmp_path, _UNDECORATED, "pass", contextlib_enrolled=True)
    (effect,) = _halt_effects(tree)
    refusal = observed_generator_object_with_refusal()
    assert effect.exception_name == refusal.exception_name
    assert effect.raised_value == refusal.message
    assert effect.exception_type_coordinate is not None


@pytest.mark.parametrize(
    ("contextlib_enrolled", "consumer"),
    ((True, WithSourceResourceSugar), (False, GeneratorWithSugar)),
)
def test_a_contextmanager_generator_still_constructs_its_manager(
    tmp_path, contextlib_enrolled, consumer
):
    opened = _imported(
        tmp_path,
        _SUPPRESSES_VALUE_ERROR,
        "raise ValueError('v')",
        contextlib_enrolled=contextlib_enrolled,
    )
    assert _function_rows(*opened) == (consumer, [("return", 7)])
