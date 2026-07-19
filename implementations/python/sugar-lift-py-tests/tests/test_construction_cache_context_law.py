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
    def __init__(self):
        self._table = {}

    def identity_key(self, site):
        return site.filename

    def _lookup(self, key):
        return self._table.get(key)

    def _publish(self, key, value):
        self._table[key] = value

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


def test_delegated_factory_constructor_cache_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
from collections import OrderedDict

class DelegatedConstructionCache:
    def __init__(self):
        self._table = OrderedDict()

    def identity_key(self, site):
        return site.filename

    def _lookup(self, key):
        return self._table.get(key)

    def _publish(self, key, value):
        self._table[key] = value

    def resolve(self, site, build_ctx):
        key = self.identity_key(site)
        known = self._lookup(key)
        if known is not None:
            return known
        value = _construct_value(site, build_ctx)
        self._publish(key, value)
        return value

def _construct_value(site, build_ctx):
    return build_ctx.build_body(site, role="statement")
"""

    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="delegated.py"
    )

    assert [offender.owner for offender in offenders] == [
        "DelegatedConstructionCache"
    ]


def test_direct_table_construction_cache_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
class DirectTableConstructionCache:
    def __init__(self):
        self._table = {}

    def identity_key(self, site):
        return site.filename

    def resolve(self, site, build_ctx):
        key = self.identity_key(site)
        known = self._table.get(key)
        if known is not None:
            return known
        value = build_ctx.build_body(site, role="statement")
        self._table[key] = value
        return value
"""

    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="direct_table.py"
    )

    assert [offender.owner for offender in offenders] == [
        "DirectTableConstructionCache"
    ]


def test_externally_driven_construction_oracle_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
from collections import OrderedDict

class ExternalConstructionOracle:
    def __init__(self):
        self._table = OrderedDict()

    def identity_key(self, site):
        return site.filename

    def get(self, key):
        return self._table.get(key)

    def put(self, key, value):
        self._table[key] = value

ORACLE = ExternalConstructionOracle()

def construct(site, build_ctx):
    oracle = ORACLE
    key = oracle.identity_key(site)
    known = oracle.get(key)
    if known is not None:
        return known
    value = build_ctx.build_body(site, role="statement")
    oracle.put(key, value)
    return value
"""

    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="external.py"
    )

    assert [offender.owner for offender in offenders] == [
        "ExternalConstructionOracle"
    ]


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


def test_delegated_installed_source_lru_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
import functools

@functools.lru_cache(maxsize=64)
def installed_source_index(module_name):
    source = installed_module_source(module_name)
    return parse_source(source)
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="installed.py"
    )
    assert [offender.owner for offender in offenders] == [
        "installed_source_index"
    ]


def test_module_context_cache_omitting_source_seat_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
from collections import OrderedDict

_FILE_CONTEXTS = OrderedDict()

def build_context(source, filename, file_cid):
    known = _FILE_CONTEXTS.get(file_cid)
    if known is not None:
        return known
    value = construct_context(source, filename)
    _remember_context(_FILE_CONTEXTS, file_cid, value)
    return value
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="context_table.py"
    )
    assert [offender.owner for offender in offenders] == ["_FILE_CONTEXTS"]


def test_opaque_construction_cycle_guard_trips_scanner() -> None:
    scanner = _scanner()
    planted = """
def resolve_install_value(target, ctx, resolving=frozenset()):
    if target in resolving:
        return None
    return build_value(target, ctx, resolving | {target})
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="cycle.py"
    )
    assert [offender.owner for offender in offenders] == [
        "resolve_install_value"
    ]


def test_context_complete_lru_table_and_loud_cycle_are_scanner_green() -> None:
    scanner = _scanner()
    clean = """
import functools
from collections import OrderedDict

@functools.lru_cache(maxsize=64)
def parsed(source, filename):
    return parse_source(source, filename)

_FILE_CONTEXTS = OrderedDict()

def build_context(source, filename, file_cid):
    key = (filename, file_cid)
    known = _FILE_CONTEXTS.get(key)
    if known is not None:
        return known
    value = construct_context(source, filename)
    _remember_context(_FILE_CONTEXTS, key, value)
    return value

def resolve_install_value(target, ctx, resolving=frozenset()):
    if target in resolving:
        return factory_panic_gap(owner="install_source_cycle")
    return build_value(target, ctx, resolving | {target})
"""
    assert (
        scanner.context_incomplete_construction_caches(
            ast.parse(clean), file="clean_families.py"
        )
        == []
    )


def test_generic_decorated_constructor_without_context_trips() -> None:
    scanner = _scanner()
    planted = """
import functools

CURRENT_CONTEXT = object()

@functools.lru_cache(maxsize=32)
def memoized_body(site):
    return CURRENT_CONTEXT.build_body(site, role="statement")
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="generic_lru.py"
    )
    assert [offender.owner for offender in offenders] == ["memoized_body"]


def test_module_table_factory_product_without_context_key_trips() -> None:
    scanner = _scanner()
    planted = """
_BODY_MEMO = {}

def resolve(site, build_ctx):
    key = site.filename
    known = _BODY_MEMO.get(key)
    if known is not None:
        return known
    body = build_ctx.build_body(site, role="statement")
    _BODY_MEMO[key] = body
    return body
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="module_table.py"
    )
    assert [offender.owner for offender in offenders] == ["_BODY_MEMO"]


def test_node_attribute_factory_product_without_context_key_trips() -> None:
    scanner = _scanner()
    planted = """
def resolve(node, site, build_ctx):
    cached = getattr(node, "_body_cache", None)
    if cached is not None:
        return cached
    body = build_ctx.build_body(site, role="statement")
    node._body_cache = (site.filename, body)
    return body
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="node_cache.py"
    )
    assert [offender.owner for offender in offenders] == ["resolve"]


def test_generic_construction_cache_syntaxes_with_context_are_green() -> None:
    scanner = _scanner()
    clean = """
import functools

@functools.lru_cache(maxsize=32)
def memoized_body(site, build_ctx):
    return build_ctx.build_body(site, role="statement")

_BODY_MEMO = {}

def resolve(site, build_ctx):
    key = (site.filename, build_ctx)
    known = _BODY_MEMO.get(key)
    if known is not None:
        return known
    body = build_ctx.build_body(site, role="statement")
    _BODY_MEMO[key] = body
    return body

def resolve_node(node, site, build_ctx):
    cached = getattr(node, "_body_cache", None)
    if cached is not None and cached[0] is build_ctx:
        return cached[1]
    body = build_ctx.build_body(site, role="statement")
    node._body_cache = (build_ctx, body)
    return body
"""
    assert (
        scanner.context_incomplete_construction_caches(
            ast.parse(clean), file="generic_clean.py"
        )
        == []
    )


def test_content_keyed_cache_with_nested_source_seat_partition_is_green() -> None:
    scanner = _scanner()
    clean = """
_FILE_PAYLOAD_CACHE = {}

def build_payload(source, file_rel, file_cid):
    seats = _FILE_PAYLOAD_CACHE.get(file_cid)
    if seats is not None and file_rel in seats:
        return seats[file_rel]
    value = build_node(source, file_rel)
    seats = _FILE_PAYLOAD_CACHE.setdefault(file_cid, {})
    seats[file_rel] = value
    return value
"""
    assert (
        scanner.context_incomplete_construction_caches(
            ast.parse(clean), file="nested_seat.py"
        )
        == []
    )


def test_module_installed_source_table_requires_context_key() -> None:
    scanner = _scanner()
    planted = """
from collections import OrderedDict

_SOURCE_CACHE = OrderedDict()

def resolve_install_source_class_bases(target, ctx):
    key = target
    known = _SOURCE_CACHE.get(key)
    if known is not None:
        return known
    value = resolve_source_bases(target, ctx)
    _SOURCE_CACHE[key] = value
    return value
"""
    offenders = scanner.context_incomplete_construction_caches(
        ast.parse(planted), file="source_table.py"
    )
    assert [offender.owner for offender in offenders] == ["_SOURCE_CACHE"]
