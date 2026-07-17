"""DigBodyOracle: sole constructor for dig body sugar structure."""

from __future__ import annotations

import importlib

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.sugar.install_source_dig import (
    DIG_BODY_ORACLE,
    INSTALL_SOURCE_VALUE_ORACLE,
    build_dig_body,
    resolve_install_source_funcdef,
)


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(filename="consumer.py", catalog=default_catalog())


def test_build_dig_body_constructs_structure_once_per_function_pin(
    tmp_path, monkeypatch
) -> None:
    """Second dig of the same FunctionDef hits body identity; does not re-factory."""
    (tmp_path / "dig_once.py").write_text(
        "def helper(x):\n"
        "    y = x + 1\n"
        "    return y\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()
    DIG_BODY_ORACLE.clear()

    ctx = _ctx()
    fn = resolve_install_source_funcdef("dig_once.helper")
    assert fn is not None

    first = build_dig_body(fn, ctx)
    constructs = DIG_BODY_ORACLE.construct_count
    hits = DIG_BODY_ORACLE.hit_count
    assert first is not None
    assert constructs >= 1

    second = build_dig_body(fn, ctx)
    assert second is not None
    assert DIG_BODY_ORACLE.construct_count == constructs
    assert DIG_BODY_ORACLE.hit_count == hits + 1
    # ContextualizedDigBody re-wraps each call; published core sugar is shared.
    assert type(first.sugar).__name__ == "ContextualizedDigBody"
    assert type(second.sugar).__name__ == "ContextualizedDigBody"
    assert first.sugar.body is second.sugar.body
