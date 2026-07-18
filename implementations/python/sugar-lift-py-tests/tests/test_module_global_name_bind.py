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
    _class_decorators_preserve_identity,
    _ctx_with_formal_binds,
    build_control_flow_body_sugar,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.floor import ImportAliasValue, StringValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.call_sugar import (
    _module_sibling_function_nodes,
    _resolve_install_source_funcdef,
)
from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
    StatementFunctionDefSugar,
)
from sugar_lift_py_tests.sugar.try_sugar import TrySugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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


def test_installed_source_body_binds_prior_identity_decorated_class() -> None:
    """Executed modules bind prior classes when every decorator preserves identity."""
    src = (
        "from pandas.util._decorators import set_module\n"
        '@set_module("pkg")\n'
        "class Result:\n"
        "    pass\n"
        "def f():\n"
        "    return Result\n"
    )
    root = SourceFragment.from_source(src, "/pkg/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/pkg/mod.py", "pkg.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"pkg.mod.f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)

    assert body_ctx.temporal.value_for("Result").name == "Result"


def test_pandas_accessor_registrar_is_authenticated_identity_decorator() -> None:
    src = (
        "import pandas as pd\n"
        '@pd.api.extensions.register_series_accessor("bad")\n'
        "class Bad:\n"
        "    pass\n"
    )
    statement = next(
        fragment
        for fragment in SourceFragment.from_source(src, "vendor.py").walk()
        if fragment.observed == "ClassDef"
    )

    assert _class_decorators_preserve_identity(statement) is True


def test_installed_source_body_rejects_prior_unknown_decorated_class() -> None:
    """A same-named local decorator cannot counterfeit the vendor contract."""
    src = (
        "def set_module(name):\n"
        "    def replace(cls):\n"
        "        return 7\n"
        "    return replace\n"
        '@set_module("pkg")\n'
        "class Result:\n"
        "    pass\n"
        "def f():\n"
        "    return Result\n"
    )
    root = SourceFragment.from_source(src, "/pkg/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/pkg/mod.py", "pkg.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"pkg.mod.f": fn.node},
    )

    with pytest.raises(FactoryPanic, match=r"bind `Result` before reducing NameSugar"):
        build_control_flow_body_sugar(fn, ctx)


def test_prior_identity_decorated_class_truthful_and_lying_refute(tmp_path) -> None:
    def project(name: str) -> Path:
        root = tmp_path / name
        root.mkdir()
        (root / "decorated_origin.py").write_text(
            "from pandas.util._decorators import set_module\n"
            '@set_module("decorated_origin")\n'
            "class Result:\n"
            "    pass\n"
            "def observed():\n"
            "    return Result\n",
            encoding="utf-8",
        )
        return root

    def source(*, truthful: bool) -> str:
        comparison = "is" if truthful else "is not"
        return (
            "from decorated_origin import observed\n"
            "def test_decorated_class_binding():\n"
            f"    assert observed() {comparison} observed()\n"
        )

    truthful = run_source_through_real_solver(
        project("truthful"), source(truthful=True)
    )
    lying = run_source_through_real_solver(project("lying"), source(truthful=False))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


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


def test_installed_source_try_optional_import_binds_name() -> None:
    """Module try/import + except None joins into install-source body temporal."""
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor import NoneValue

    src = (
        "try:\n"
        "    import optional_mod\n"
        "except ImportError:\n"
        "    optional_mod = None\n"
        "def f():\n"
        "    return optional_mod\n"
    )
    root = SourceFragment.from_source(src, "/opt/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/opt/mod.py", "opt.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"opt.mod.f": fn.node},
    )
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    bindings = {binding.name: binding.value for binding in body_ctx.temporal.bindings}
    assert "optional_mod" in bindings, bindings
    value = bindings["optional_mod"]
    assert isinstance(value, GuardedValue)
    assert isinstance(value.when_false, NoneValue)
    assert isinstance(value.when_true, ImportAliasValue)


def test_installed_source_try_loads_earlier_module_dependency() -> None:
    src = (
        "seed = 7\n"
        "try:\n"
        "    alias = seed\n"
        "except ValueError:\n"
        "    alias = 7\n"
        "def f():\n"
        "    return alias\n"
    )
    root = SourceFragment.from_source(src, "/ordered/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/ordered/mod.py", "ordered.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"ordered.mod.f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)

    assert body_ctx.temporal.value_for("alias") is not None


def test_installed_source_try_cannot_load_later_module_dependency() -> None:
    src = (
        "try:\n"
        "    alias = seed\n"
        "except ValueError:\n"
        "    alias = 7\n"
        "seed = 7\n"
        "def f():\n"
        "    return alias\n"
    )
    root = SourceFragment.from_source(src, "/wrong_order/mod.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/wrong_order/mod.py", "wrong_order.mod.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"wrong_order.mod.f": fn.node},
    )

    with pytest.raises(FactoryPanic, match=r"bind `seed` before reducing NameSugar"):
        _ctx_with_formal_binds(fn, ctx)


def test_installed_source_body_binds_authenticated_module_file() -> None:
    src = "def f():\n    return __file__\n"
    root = SourceFragment.from_source(src, "/vendor/pkg/origin.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/vendor/pkg/origin.py", "vendor.pkg.origin.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"vendor.pkg.origin.f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)

    assert body_ctx.temporal.value_for("__file__") == StringValue(
        "/vendor/pkg/origin.py"
    )


def test_module_try_dependency_binds_authenticated_module_file() -> None:
    """Loader names discovered through a selected statement join are available."""
    src = (
        "try:\n"
        "    alias = __file__\n"
        "except ValueError:\n"
        '    alias = "fallback"\n'
        "def f():\n"
        "    return alias\n"
    )
    root = SourceFragment.from_source(src, "/vendor/pkg/origin.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    _tag_install_source(fn, src, "/vendor/pkg/origin.py", "vendor.pkg.origin.f")
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"vendor.pkg.origin.f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)

    assert body_ctx.temporal.value_for("alias")


def test_untagged_source_body_cannot_invent_module_file() -> None:
    src = "def f():\n    return __file__\n"
    root = SourceFragment.from_source(src, "/unowned/origin.py")
    fn = next(
        fragment
        for fragment in root.walk()
        if fragment.observed == "FunctionDef" and fragment.function_name() == "f"
    )
    ctx = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        name_resolver={"f": fn.node},
    )

    body_ctx = _ctx_with_formal_binds(fn, ctx)

    with pytest.raises(FactoryPanic, match=r"bind `__file__` before reducing"):
        body_ctx.temporal.value_for("__file__")


def test_module_loader_file_witness_refutes_wrong_twin(tmp_path: Path) -> None:
    pair = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "statement_function_def_module_loader_file"
    )
    origin = "def f():\n    return __file__ == __file__\n"
    truthful_project = tmp_path / "truthful"
    truthful_project.mkdir()
    (truthful_project / "module_loader_origin.py").write_text(origin, encoding="utf-8")
    lying_project = tmp_path / "lying"
    lying_project.mkdir()
    (lying_project / "module_loader_origin.py").write_text(origin, encoding="utf-8")

    truthful = run_source_through_real_solver(truthful_project, pair.truthful.source)
    lying = run_source_through_real_solver(lying_project, pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_module_try_dependency_prefix_witness_refutes_wrong_twin(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in TrySugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "module_try_dependency_prefix"
    )
    truthful_project = tmp_path / "truthful"
    truthful_project.mkdir()
    origin = (
        "seed = 7\n"
        "try:\n"
        "    alias = seed\n"
        "finally:\n"
        "    marker = 1\n"
        "def f():\n"
        "    return alias\n"
    )
    (truthful_project / "temporal_try_origin.py").write_text(origin, encoding="utf-8")
    lying_project = tmp_path / "lying"
    lying_project.mkdir()
    (lying_project / "temporal_try_origin.py").write_text(origin, encoding="utf-8")

    truthful = run_source_through_real_solver(truthful_project, pair.truthful.source)
    lying = run_source_through_real_solver(lying_project, pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_minimal_module_global_without_sugar_tag_does_not_seed() -> None:
    """Without install-source tags, formal-only temporal (no silent ambient seed)."""
    src = 'GLOBAL = b"untagged"\n' "def f(s):\n" "    return s.translate(GLOBAL)\n"
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
