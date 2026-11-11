"""A ``@contextlib.contextmanager`` generator constructs under contextlib's protocol.

A same-module ``@contextmanager`` generator used as a With head had no import
receipt, so resolution left it ``runtime-selected`` and the generator protocol
was never applied. It now publishes through the same generator-backed door as
an imported one, and every body exit runs ``_GeneratorContextManager.__exit__``
(``generator_manager_exit``): a raise is thrown in at the yield and split by
the generator's own ``except`` arms; completion resumes it and it must stop.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    SourceDerivedGeneratorResourceRefV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.generator_manager_exit import observed_exit_refusals
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import With

import test_contextlib_suppress_source_exit_faces as opener
from test_contextlib_suppress_source_exit_faces import _corpus


_SUPPRESSES_VALUE_ERROR = (
    "from contextlib import contextmanager\n"
    "@contextmanager\n"
    "def cm():\n"
    "    try:\n"
    "        yield 1\n"
    "    except ValueError:\n"
    "        pass\n"
)


def _with(tmp_path: Path, source: str):
    source_file = opener._open(_corpus(tmp_path, source))
    return source_file, next(n for n in source_file.nodes() if isinstance(n, With))


def _imported(tmp_path: Path, implementation: str, body: str, *, contextlib_enrolled):
    """``from arbitrary import cm`` over an installed distribution's manager."""
    from test_returned_resource_with_construction import (
        _contextmanager_dependency_graphs,
        _distribution,
    )

    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.tree import SourceFile

    dist = _distribution(tmp_path, implementation, exported="cm")
    consumer = (
        "from arbitrary import cm\n"
        f"def f():\n    with cm():\n        {body}\n    return 7\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    roster = {dist.metadata["Name"]}
    if contextlib_enrolled:
        roster.add("cpython-stdlib:contextlib")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": dist},
        artifact_graph_cache=(
            _contextmanager_dependency_graphs() if contextlib_enrolled else None
        ),
        session=SourceResolutionSession(enrolled_distributions=frozenset(roster)),
    )
    return tree, next(n for n in tree.nodes() if isinstance(n, With))


def _exits(tmp_path: Path, source: str):
    _source_file, with_node = _with(tmp_path, source)
    return _faces(with_node.sugar())


def _faces(sugar):
    # GeneratorWithSugar answers in the linear view (halts ride as Incomplete
    # entries); promotion is how every consumer reads them back as faces.
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts

    return promote_raise_halts(outcome_to_exitset(sugar.desugar()))


def _halts(exits):
    return [face for face in exits.exits if isinstance(face, Halted)]


def _leaves_normally(exits):
    return [
        face
        for face in exits.exits
        if isinstance(face, Completed) and face.value.can_fall_through
    ]


def _raised(exits):
    """(class, message) per raise; a source raise's message is its own value."""
    return sorted(
        (
            face.effect.exception_name,
            face.effect.raised_value
            if isinstance(face.effect.raised_value, str)
            else None,
        )
        for face in _halts(exits)
        if isinstance(face.effect, RaiseEffect)
    )


def _manager(header: str, body: str) -> str:
    return f"{header}def f():\n    with cm():\n        {body}\n    return 7\n"


def test_local_contextmanager_publishes_the_generator_resource_ref(tmp_path):
    source_file, with_node = _with(
        tmp_path, _manager(_SUPPRESSES_VALUE_ERROR, "pass")
    )
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    assert type(ref) is SourceDerivedGeneratorResourceRefV1
    assert type(with_node.sugar()) is WithSourceResourceSugar


def test_try_finally_runs_and_the_body_raise_propagates(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            "import contextlib\n"
            "@contextlib.contextmanager\n"
            "def cm(a=1):\n"
            "    try:\n"
            "        yield a\n"
            "    finally:\n"
            "        pass\n",
            "raise KeyError('k')",
        ),
    )
    assert _raised(exits) == [("KeyError", None)]
    assert _leaves_normally(exits) == []


def _function_rows(source_file, with_node):
    """Every return/halt ``f`` can leave by (the reader both consumers share)."""
    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    rows = []
    for face in outcome_to_exitset(func.sugar().desugar()).exits:
        if isinstance(face, Halted):
            rows.append(("halt", getattr(face.effect, "exception_name", None)))
            continue
        for entry in getattr(getattr(face.value, "record", None), "statements", ()):
            name = type(entry).__name__
            if name in ("ReturnValue", "GuardedReturn") and "value=7)" in repr(
                entry.value
            ):
                rows.append(("return", 7))
            elif name == "Incomplete":
                rows.append(("halt", getattr(entry.effect, "exception_name", None)))
    return type(with_node.sugar()), sorted(rows, key=lambda row: (row[0], str(row[1])))


@pytest.mark.parametrize(
    ("road", "consumer"),
    (
        ("local", WithSourceResourceSugar),
        ("imported", WithSourceResourceSugar),
        # contextlib's source off population: the import road seats the
        # generator frame and GeneratorWithSugar consumes it under the same law.
        ("imported-off-population", GeneratorWithSugar),
    ),
)
@pytest.mark.parametrize(
    ("body", "rows"),
    (
        ("raise ValueError('v')", [("return", 7)]),
        ("raise TypeError('t')", [("halt", "TypeError")]),
        ("pass", [("return", 7)]),
    ),
)
def test_except_arm_suppresses_only_its_exception(tmp_path, road, consumer, body, rows):
    if road == "local":
        opened = _with(tmp_path, _manager(_SUPPRESSES_VALUE_ERROR, body))
    else:
        opened = _imported(
            tmp_path,
            _SUPPRESSES_VALUE_ERROR,
            body,
            contextlib_enrolled=road == "imported",
        )
    assert _function_rows(*opened) == (consumer, rows)


def test_undetermined_c_call_raise_splits_on_the_generator_except_arm(tmp_path):
    exits = _exits(
        tmp_path,
        _manager("import decimal\n" + _SUPPRESSES_VALUE_ERROR, "decimal.getcontext()"),
    )
    (halt,) = _halts(exits)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    normal = _leaves_normally(exits)
    # Completed call, and the raise the arm caught: never decided either way.
    assert len(normal) == 2
    caught = [face for face in normal if "adt.is_python_type" in repr(face.guard)]
    assert len(caught) == 1
    assert "adt.is_python_type" in repr(halt.guard)
    assert "'not'" in repr(halt.guard)


def test_a_second_yield_after_completion_raises_generator_didnt_stop(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def cm():\n"
            "    yield 1\n"
            "    yield 2\n",
            "pass",
        ),
    )
    refusals = observed_exit_refusals()
    assert _raised(exits) == [("RuntimeError", refusals.did_not_stop)]
    assert _leaves_normally(exits) == []


def test_a_yield_after_the_caught_throw_raises_didnt_stop_after_throw(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            _SUPPRESSES_VALUE_ERROR + "    yield 2\n", "raise ValueError('v')"
        ),
    )
    refusals = observed_exit_refusals()
    assert _raised(exits) == [("RuntimeError", refusals.did_not_stop_after_throw)]
    assert _leaves_normally(exits) == []


def test_reraising_the_thrown_exception_propagates_it(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def cm():\n"
            "    try:\n"
            "        yield 1\n"
            "    except ValueError:\n"
            "        raise\n",
            "raise ValueError('v')",
        ),
    )
    assert _raised(exits) == [("ValueError", None)]
    assert _leaves_normally(exits) == []


def test_stop_iteration_from_the_generator_becomes_runtime_error(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def cm():\n"
            "    yield 1\n"
            "    raise StopIteration\n",
            "pass",
        ),
    )
    refusals = observed_exit_refusals()
    assert _raised(exits) == [("RuntimeError", refusals.stop_iteration_conversion)]


def test_a_body_stop_iteration_propagates_as_itself(tmp_path):
    exits = _exits(
        tmp_path,
        _manager(
            "from contextlib import contextmanager\n"
            "@contextmanager\n"
            "def cm():\n"
            "    yield 1\n",
            "raise StopIteration",
        ),
    )
    assert [name for name, _ in _raised(exits)] == ["StopIteration"]
    assert _leaves_normally(exits) == []


def test_an_undecorated_local_generator_never_constructs_a_manager(tmp_path):
    source_file, with_node = _with(
        tmp_path, "def cm():\n    yield 1\ndef f():\n    with cm():\n        pass\n"
    )
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    assert not any(
        isinstance(ref, SourceDerivedGeneratorResourceRefV1) for ref in refs.values()
    )
    # ``cm()`` returns a generator object, which has no ``__enter__``: the
    # With raises the interpreter's own TypeError before enter and body
    # (#7595), never a manager and never a runtime-selected gap.
    from sugar_lift_py_tests.sugar.generator_with_sugar import (
        GeneratorObjectWithSugar,
    )

    sugar = with_node.sugar()
    assert isinstance(sugar, GeneratorObjectWithSugar)
    assert sugar.object_kind == "generator"


def test_exit_refusal_texts_are_contextlibs_own():
    refusals = observed_exit_refusals()

    @contextlib.contextmanager
    def twice():
        yield
        yield

    with pytest.raises(RuntimeError) as raised:
        with twice():
            pass
    assert str(raised.value) == refusals.did_not_stop
    assert refusals.exception_name == "RuntimeError"
