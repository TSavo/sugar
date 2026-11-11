"""``with f(...)`` over this module's own plain factory is cited as its callee.

``pandas.io.common`` defines and uses its own factory::

    def urlopen(*args, **kwargs):
        import urllib.request
        return urllib.request.urlopen(*args, **kwargs)

    ...
        with urlopen(req_info) as req:

The local ``urlopen`` has no import receipt, so no route derived a manager
for the With and it panicked ``runtime-selected``.  Law: the factory returns
exactly what its trailing call returns, so the With enters that call's
result.  The callee is authenticated by the import value receipt at the
callee expression (a ``*args, **kwargs`` call carries no call-target row) and
named by the export door; off the enrolled population (CPython's
``urllib.request``) the manager is cited, never materialized: enter, exit and
suppression stay open and two-faced, and the head still runs the factory.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

from test_contextmanager_generator_protocol import _function_rows

_STARRED_LOCAL_IMPORT_FACTORY = (
    "def cm(*args, **kwargs):\n"
    "    import contextlib\n"
    "    return contextlib.nullcontext(*args, **kwargs)\n"
)


def _lift(tmp_path: Path, factory: str, body: str = "pass"):
    source = factory + f"def f():\n    with cm(1):\n        {body}\n    return 7\n"
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    return tree, next(n for n in tree.nodes() if isinstance(n, With)), context


def test_same_module_factory_is_cited_as_its_vendor_callee(tmp_path: Path) -> None:
    tree, with_node, context = _lift(tmp_path, _STARRED_LOCAL_IMPORT_FACTORY)
    (ref,) = context.source_derived_contract_refs.values()
    assert isinstance(ref, OpaqueCitedContextManagerRefV1)
    assert ref.target_name == "python:contextlib.nullcontext"
    consumer, rows = _function_rows(tree, with_node)
    assert consumer is WithOpaqueCitedManagerSugar
    # Open protocol: construction, enter and exit may each raise; the body
    # falls through to the return.
    assert ("return", 7) in rows
    assert ("halt", None) in rows


def test_body_raise_still_propagates_through_the_cited_factory(tmp_path: Path) -> None:
    tree, with_node, _context = _lift(
        tmp_path, _STARRED_LOCAL_IMPORT_FACTORY, "raise KeyError(1)"
    )
    _consumer, rows = _function_rows(tree, with_node)
    assert ("halt", "KeyError") in rows
    assert ("return", 7) not in rows


def test_factory_with_more_than_a_trailing_return_is_not_cited(tmp_path: Path) -> None:
    # Lying twin: a factory that computes before returning does not hand back
    # just its trailing call's result path, so this route does not claim it.
    factory = (
        "def cm(*args):\n"
        "    import contextlib\n"
        "    if args:\n"
        "        args = ()\n"
        "    return contextlib.nullcontext(*args)\n"
    )
    _tree, _with_node, context = _lift(tmp_path, factory)
    assert not any(
        isinstance(ref, OpaqueCitedContextManagerRefV1)
        for ref in context.source_derived_contract_refs.values()
    )


def test_dependency_frame_over_its_own_factory_is_cited(tmp_path: Path) -> None:
    # ``pandas.io.pickle`` enters ``get_handle``, whose body enters
    # ``with urlopen(...)`` over ``pandas.io.common``'s own factory.  The
    # dependency frame takes the same route, fed by that module's receipts.
    from test_contextmanager_generator_protocol import _imported

    implementation = (
        "def opener(*args, **kwargs):\n"
        "    import contextlib\n"
        "    return contextlib.nullcontext(*args, **kwargs)\n"
        "import contextlib\n"
        "@contextlib.contextmanager\n"
        "def cm():\n"
        "    with opener(1):\n"
        "        pass\n"
        "    yield 1\n"
    )
    tree, with_node = _imported(tmp_path, implementation, "pass", contextlib_enrolled=False)
    _consumer, rows = _function_rows(tree, with_node)
    assert ("return", 7) in rows
