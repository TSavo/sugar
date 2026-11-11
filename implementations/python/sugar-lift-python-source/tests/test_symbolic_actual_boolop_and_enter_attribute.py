"""Two open reads ``pandas.io.common.get_handle`` makes, each two-faced.

``with get_handle(path, "w", storage_options=storage_options)`` in
``pandas.io.pickle`` derives ``get_handle`` with the caller's actual, a bare
symbolic term whose runtime type nothing decided.  Inside, get_handle writes:

* ``storage_options = storage_options or {}`` -- the BoolOp producer refused
  ``bool(<symbolic>)`` (``boolean_operation_exception_floor: SymbolicValue
  or``) and voided the manager;
* ``with urlopen(req_info) as req: req.headers`` -- an attribute read on the
  enter result's own ``#enter_result`` coordinate panicked ("implement
  EffectCoordinate.attribute").

Under the #7585 law each read completes only under its own atom
(``python:truth.completes`` / ``python:unknown_attribute.completes``) and
halts with an ``UndeterminedRaiseEffect`` under the complement.  No truth,
attribute value or exception identity is invented.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

from test_contextmanager_generator_protocol import _function_rows

_CM = (
    "class CM:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
)


def _consumer_rows(tmp_path: Path, implementation: str, consumer: str):
    from test_returned_resource_with_construction import _distribution

    dist = _distribution(tmp_path, implementation, exported="cm")
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": dist},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({dist.metadata["Name"]})
        ),
    )
    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    return _function_rows(tree, with_node)[1]


def test_symbolic_actual_truth_in_or_halts_or_selects(tmp_path: Path) -> None:
    implementation = _CM + (
        "def cm(options=None):\n"
        "    options = options or {}\n"
        "    return CM()\n"
    )
    consumer = (
        "from arbitrary import cm\n"
        "def f(opts):\n    with cm(opts):\n        pass\n    return 7\n"
    )
    rows = _consumer_rows(tmp_path, implementation, consumer)
    assert ("return", 7) in rows
    assert ("halt", None) in rows


def test_decided_actual_truth_adds_no_halt(tmp_path: Path) -> None:
    # Lying twin: a decided operand's truth cannot raise.
    implementation = _CM + (
        "def cm(options=None):\n"
        "    options = options or {}\n"
        "    return CM()\n"
    )
    consumer = (
        "from arbitrary import cm\n"
        "def f():\n    with cm(0):\n        pass\n    return 7\n"
    )
    assert _consumer_rows(tmp_path, implementation, consumer) == [("return", 7)]


def test_attribute_on_cited_enter_result_halts_or_completes(tmp_path: Path) -> None:
    from test_same_module_factory_manager import _lift

    factory = (
        "def cm(*args, **kwargs):\n"
        "    import contextlib\n"
        "    return contextlib.nullcontext(*args, **kwargs)\n"
    )
    source_body = "pass"
    tree, with_node, _context = _lift(tmp_path, factory, source_body)
    baseline = set(_function_rows(tree, with_node)[1])

    other = tmp_path / "attr"
    other.mkdir()
    source = factory + (
        "def f():\n    with cm(1) as r:\n        y = r.headers\n    return 7\n"
    )
    path = other / "consumer.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    attr_tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        attr_tree,
        root=other,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    attr_with = next(n for n in attr_tree.nodes() if isinstance(n, With))
    rows = _function_rows(attr_tree, attr_with)[1]
    assert ("return", 7) in rows
    assert ("halt", None) in rows
    # The read adds a halt face of its own beyond the cited protocol's.
    assert len(rows) > len(_function_rows(tree, with_node)[1])
    assert baseline <= set(rows)
