"""An async method is a class member through the same FunctionDef door.

``contextlib.nullcontext`` carries ``async def __aenter__/__aexit__`` beside
the sync protocol. The class-member door refused every class with an async
member ("async arm not written yet"), so the first module enrolled under
plan Cut 1 stopped at ``force-floor`` before touching ``__enter__``.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar
from sugar_source_tree.nodes import AsyncFunctionDef, ClassDef
from sugar_source_tree.reporter import CollectingReporter

SOURCE = (
    "class Both:\n"
    "    def __init__(self, result=None):\n"
    "        self.result = result\n"
    "    def __enter__(self):\n"
    "        return self.result\n"
    "    def __exit__(self, *excinfo):\n"
    "        pass\n"
    "    async def __aenter__(self):\n"
    "        return self.result\n"
    "    async def __aexit__(self, *excinfo):\n"
    "        pass\n"
)


def _class(tmp_path):
    path = tmp_path / "both.py"
    path.write_text(SOURCE)
    source_file = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    return next(n for n in source_file.nodes() if isinstance(n, ClassDef))


def test_async_members_construct_through_the_function_door(tmp_path) -> None:
    cls = _class(tmp_path)
    async_member = next(m for m in cls.body if isinstance(m, AsyncFunctionDef))
    member = cls._construct_class_method_member(async_member)
    assert member.name == "__aenter__"
    assert isinstance(member.body, FunctionUniverseSugar)
    assert member.source_call_frame is not None and member.source_call_frame.owner is async_member


def test_class_with_async_members_constructs(tmp_path) -> None:
    """The sync protocol's owner no longer refuses over a member it never enters."""
    cls = _class(tmp_path)
    sugar = cls.sugar()
    names = {m.name for m in getattr(sugar, "methods", ()) or ()} if hasattr(sugar, "methods") else None
    assert sugar is not None
    if names is not None:
        assert {"__enter__", "__exit__", "__aenter__", "__aexit__"} <= names
