from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ObjectValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
    DeferredStatementStructureOracle,
)


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "construction_cache_context_law.py"


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "construction_cache_context_law", _SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    return scanner


def _class_definition(value: int) -> ast.ClassDef:
    node = ast.parse(
        "class Foo:\n"
        "    def __init__(self):\n"
        f"        self.x = {value}\n"
    ).body[0]
    assert isinstance(node, ast.ClassDef)
    return node


def _context(value: int) -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="same.py",
        catalog=default_catalog(),
        name_resolver={"Foo": _class_definition(value)},
    )


def _returned_x(body, ctx: FactoryBuildContext) -> int:
    returned = complete_value(
        body.reduce(ctx), owner="construction-cache wrong-context twin"
    )
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, ObjectValue)
    fields = {field.name: field.value for field in returned.value.fields}
    assert isinstance(fields["x"], TermValue)
    assert isinstance(fields["x"].value, int)
    return fields["x"].value


def test_deferred_structure_cache_separates_factory_recognition_contexts() -> None:
    site = next(
        fragment
        for fragment in SourceFragment.from_source(
            "def f():\n"
            "    return Foo()\n",
            "same.py",
        ).walk()
        if fragment.observed == "Return"
    )
    oracle = DeferredStatementStructureOracle()
    first_ctx = _context(1)
    second_ctx = _context(2)

    first = oracle.resolve(site, first_ctx)
    constructs_after_first = oracle.construct_count
    hits_after_first = oracle.hit_count
    same_context = oracle.resolve(site, first_ctx)

    assert same_context is first
    assert oracle.construct_count == constructs_after_first
    assert oracle.hit_count == hits_after_first + 1

    second = oracle.resolve(site, second_ctx)
    cached_second_x = _returned_x(second, second_ctx)
    fresh_second_x = _returned_x(
        DeferredStatementStructureOracle().resolve(site, second_ctx),
        second_ctx,
    )

    assert second is not first
    assert cached_second_x == fresh_second_x == 2


def test_context_omitting_factory_structure_cache_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
class BadConstructionCache:
    def identity_key(self, site):
        return site.filename

    def resolve(self, site, build_ctx):
        key = self.identity_key(site)
        known = self._lookup(key)
        if known is not None:
            return known
        body = build_ctx.build_body(site, role="statement")
        self._publish(key, body)
        return body
"""

    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="planted.py"
    )

    assert len(offenders) == 1
    assert offenders[0].owner == "BadConstructionCache"
    assert "factory-recognition context" in offenders[0].reason


def test_context_keyed_factory_structure_cache_is_scanner_green() -> None:
    scanner = _scanner()
    clean = """
class GoodConstructionCache:
    def identity_key(self, site, build_ctx):
        return (site.filename, build_ctx.recognition_identity())

    def resolve(self, site, build_ctx):
        key = self.identity_key(site, build_ctx)
        known = self._lookup(key)
        if known is not None:
            return known
        body = build_ctx.build_body(site, role="statement")
        self._publish(key, body)
        return body
"""

    assert (
        scanner.context_incomplete_construction_caches(
            ast.parse(clean), file="clean.py"
        )
        == []
    )
