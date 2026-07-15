"""Module-level Name globals bind during install-source body dig.

Open dig of ``base64.urlsafe_b64encode`` (and any callee tagged with
``_sugar_file`` / ``_sugar_source``) must seed temporal with module-level
``Name = ...`` Assign constants so body Names like
``_urlsafe_encode_translation`` reduce instead of TemporalContext floor-gap
``bind name before reducing NameSugar``.

Systemic: seed from the callee module source, not an itsdangerous-only path.
Does not flip ``nested_external_bridge`` default; ambient strip stays closed.
"""

from __future__ import annotations

import base64
import inspect
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.factory.sugar_constructors import (
    IncompleteFunctionBody,
    _ctx_with_formal_binds,
    build_control_flow_body_sugar,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.floor import ImportAliasValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.call_sugar import (
    _module_sibling_function_nodes,
    _resolve_install_source_funcdef,
)


def _tag_install_source(
    fn: SourceFragment, source: str, path: str, qualified_name: str = "pkg.mod.f"
) -> SourceFragment:
    fn.node._sugar_source = source  # type: ignore[attr-defined]
    fn.node._sugar_file = path  # type: ignore[attr-defined]
    fn.node._sugar_bridge_name = qualified_name  # type: ignore[attr-defined]
    return fn


def test_minimal_module_global_binds_on_body_dig() -> None:
    """GLOBAL = b\"x\"; def f(s): return s.translate(GLOBAL) — Name binds."""
    src = 'GLOBAL = b"x"\n' "def f(s):\n" "    return s.translate(GLOBAL)\n"
    root = SourceFragment.from_source(src, "mod_globals.py")
    fn = next(
        f
        for f in root.walk()
        if f.observed == "FunctionDef" and f.function_name() == "f"
    )
    _tag_install_source(fn, src, "mod_globals.py")

    ctx = FactoryBuildContext(
        filename="mod_globals.py",
        catalog=default_catalog(),
        name_resolver={"f": fn.node},
    )
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    bound = {b.name for b in body_ctx.temporal.bindings}
    assert "GLOBAL" in bound, bound
    assert "s" in bound, bound

    sugar = build_control_flow_body_sugar(fn, ctx)
    blob = str(sugar.constraint_formulas())
    assert "call:translate" in blob or "translate" in blob, blob
    # Must not leave GLOBAL as an unbound free name gap.
    assert "bind `GLOBAL`" not in blob


def test_installed_source_body_binds_needed_sibling_assignment_and_import() -> None:
    """Source-owned globals include imports without executing the target module."""
    module_name = "_sugar_static_module_probe.shared"
    assert module_name not in sys.modules
    src = (
        'raise RuntimeError("installed source must not execute")\n'
        "import provider_alpha as provider\n"
        "TOKEN = 11\n"
        "def f(x):\n"
        "    return provider.select(TOKEN, x)\n"
    )
    root = SourceFragment.from_source(src, "/alpha/shared.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/alpha/shared.py", f"{module_name}.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        temporal=FactoryBuildContext(
            filename="ambient.py", catalog=default_catalog()
        ).temporal.bind_value("AMBIENT", SymbolicValue(make_var("AMBIENT"))),
        name_resolver={"f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)
    bindings = {binding.name: binding.value for binding in body_ctx.temporal.bindings}
    assert set(bindings) == {"provider", "TOKEN", "x"}, bindings
    assert isinstance(bindings["provider"], ImportAliasValue)
    assert bindings["provider"].import_target == "provider_alpha"
    assert "AMBIENT" not in bindings
    assert "len" not in bindings  # no ambient builtins namespace flood
    assert module_name not in sys.modules
    assert "provider_alpha" not in sys.modules


def test_unsupported_installed_source_global_remains_loud() -> None:
    src = "TOKEN = UNSUPPORTED\ndef f():\n    return TOKEN\n"
    root = SourceFragment.from_source(src, "/unsupported/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/unsupported/mod.py", "unsupported.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"unsupported.mod.f": fn.node},
    )

    with pytest.raises(
        FactoryPanic, match=r"bind `UNSUPPORTED` before reducing NameSugar"
    ):
        build_control_flow_body_sugar(fn, ctx)


def test_minimal_module_global_without_sugar_tag_does_not_seed() -> None:
    """Without install-source tags, formal-only temporal (no silent ambient seed)."""
    src = (
        'GLOBAL = b"untagged"\n'
        "def f(s):\n"
        "    return s.translate(GLOBAL)\n"
    )
    root = SourceFragment.from_source(src, "mod_globals.py")
    fn = next(
        f
        for f in root.walk()
        if f.observed == "FunctionDef" and f.function_name() == "f"
    )
    ambient = FactoryBuildContext(
        filename="ambient.py", catalog=default_catalog()
    ).temporal.bind_value("AMBIENT", SymbolicValue(make_var("AMBIENT")))
    ctx = FactoryBuildContext(
        filename="mod_globals.py",
        catalog=default_catalog(),
        temporal=ambient,
        name_resolver={"f": fn.node},
    )
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    bound = {b.name for b in body_ctx.temporal.bindings}
    assert bound == {"s"}, bound


def test_same_leaf_installed_modules_cannot_cross_bind_globals() -> None:
    """Qualified source ownership, not ``shared.py`` leaf identity, selects globals."""

    def body_context(source: str, path: str, qualified_name: str):
        root = SourceFragment.from_source(source, path)
        fn = next(
            fragment
            for fragment in root.walk()
            if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
        )
        _tag_install_source(fn, source, path, qualified_name)
        ctx = FactoryBuildContext(
            filename="consumer.py",
            catalog=default_catalog(),
            name_resolver={qualified_name: fn.node},
        )
        return fn, _ctx_with_formal_binds(fn, ctx)

    alpha_fn, alpha = body_context(
        'TOKEN = "alpha"\ndef f():\n    return TOKEN\n',
        "/alpha/shared.py",
        "alpha.shared.f",
    )
    beta_fn, beta = body_context(
        'TOKEN = "beta"\ndef f():\n    return TOKEN\n',
        "/beta/shared.py",
        "beta.shared.f",
    )

    alpha_token = alpha.temporal.value_for("TOKEN")
    beta_token = beta.temporal.value_for("TOKEN")
    assert str(alpha_token.to_term(owner="test")) != str(
        beta_token.to_term(owner="test")
    )
    assert alpha_fn.node._sugar_bridge_name == "alpha.shared.f"  # type: ignore[attr-defined]
    assert beta_fn.node._sugar_bridge_name == "beta.shared.f"  # type: ignore[attr-defined]


def test_urlsafe_encode_translation_binds_from_install_source() -> None:
    """base64.urlsafe_b64encode body sees ``_urlsafe_encode_translation``."""
    resolved = _resolve_install_source_funcdef("base64.urlsafe_b64encode")
    assert resolved is not None
    # Prefer full-module sibling node when available (real file path + source).
    siblings = _module_sibling_function_nodes("base64")
    node = siblings.get("base64.urlsafe_b64encode") or siblings.get("urlsafe_b64encode")
    if node is not None:
        fn = SourceFragment.from_node(
            node, getattr(node, "_sugar_file", inspect.getsourcefile(base64) or "")
        )
    else:
        fn = resolved
        path = inspect.getsourcefile(base64)
        assert path is not None
        _tag_install_source(fn, Path(path).read_text(encoding="utf-8"), path)

    assert getattr(fn.node, "_sugar_file", None) or getattr(
        fn.node, "_sugar_source", None
    )

    ctx = FactoryBuildContext(
        filename=getattr(fn.node, "_sugar_file", "base64.py"),
        catalog=default_catalog(),
        name_resolver=siblings or {"urlsafe_b64encode": fn.node},
    )
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    bound = {b.name for b in body_ctx.temporal.bindings}
    assert "_urlsafe_encode_translation" in bound, bound
    assert "s" in bound, bound

    # Body dig may still Incomplete on nested b64encode asserts; the Name must
    # not be the first failure mode.
    try:
        sugar = build_control_flow_body_sugar(fn, ctx)
        blob = str(sugar.constraint_formulas())
        assert "_urlsafe_encode_translation" not in blob or "call:translate" in blob
    except IncompleteFunctionBody as exc:
        reason = str(exc.incomplete.effect)
        assert "bind `_urlsafe_encode_translation`" not in reason, reason
        assert not (
            isinstance(exc.incomplete, Incomplete)
            and getattr(exc.incomplete.effect, "observed", None)
            == "_urlsafe_encode_translation"
        ), reason


def test_nested_external_bridge_default_still_false() -> None:
    """Regression: do not flip nested_external_bridge default (logo safety)."""
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    assert getattr(ctx, "nested_external_bridge", False) is False
