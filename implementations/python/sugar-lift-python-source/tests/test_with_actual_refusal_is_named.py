"""A manager call's actual that refuses by name refuses the With, not the file.

``with get_handle(self.filepath_or_buffer, ...)`` (pandas io/formats/csvs.py)
reads ``self.filepath_or_buffer`` on a receiver whose type nothing decided:
the attribute floor raises its named ``SugarNotWritten``.  Building the
manager's actuals let it escape as a file terminal once get_handle's frame
constructed (#7665); it is the With's ``incomplete-call-actuals`` gap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.panic import SourceTreePanic


_IMPL = """class M:
    def __init__(self, v):
        self.v = v
    def __enter__(self):
        return 1
    def __exit__(self, *exc):
        return False
def cm(v):
    return M(v)
"""


def _tree(tmp_path: Path, consumer: str):
    from test_returned_resource_with_construction import _distribution

    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.tree import SourceFile

    dist = _distribution(tmp_path, _IMPL, exported="cm")
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": dist},
        artifact_graph_cache=None,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({dist.metadata["Name"]})
        ),
    )
    return tree


def test_an_undecided_receiver_actual_is_the_withs_named_gap(tmp_path) -> None:
    from sugar_source_tree.nodes import With

    tree = _tree(
        tmp_path,
        "from arbitrary import cm\n"
        "class W:\n"
        "    def save(self):\n"
        "        with cm(self.path):\n"
        "            pass\n",
    )
    with_node = next(n for n in tree.nodes() if isinstance(n, With))
    with pytest.raises(SourceTreePanic, match="incomplete-call-actuals"):
        with_node.sugar()


def test_issubclass_on_an_operand_without_class_testimony_is_named(monkeypatch) -> None:
    from types import SimpleNamespace

    from sugar_lift_py_tests.floor.builtin_semantic_callable import (
        BuiltinSemanticCallable,
    )
    from sugar_source_tree.panic import SugarNotWritten

    callee = BuiltinSemanticCallable(operation="python.issubclass")
    monkeypatch.setattr(
        BuiltinSemanticCallable, "_resolve_type_operand", lambda self, v, site: v
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    site = SourceFragmentCoordinateV1("blake3-512:" + "0" * 128, 1, 0, 1, 4)
    operation = SimpleNamespace(
        arguments=(object(), object()), keyword_names=(), site=site
    )
    with pytest.raises(SugarNotWritten, match="without class testimony"):
        callee.callable_application_with(operation, None)
