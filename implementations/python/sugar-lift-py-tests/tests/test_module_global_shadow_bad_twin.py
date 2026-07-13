"""#3958 free-name bad-twin: local/formal shadow beats module-global seed.

Module-level ``Name = ...`` binds into dig temporal for free Names. Python
shadowing must win:

- body ``GLOBAL = b\"local\"`` after ``GLOBAL = b\"module\"`` → dig uses local
- formal named ``GLOBAL`` → dig uses formal, not module constant

Without these twins, free-name seeding can silent-misbind shadowed names.
"""

from __future__ import annotations

from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.factory.sugar_constructors import (
    _ctx_with_formal_binds,
    build_control_flow_body_sugar,
)
from sugar_lift_py_tests.floor import SymbolicValue


def _tag(fn: SourceFragment, source: str, path: str) -> SourceFragment:
    fn.node._sugar_source = source  # type: ignore[attr-defined]
    fn.node._sugar_file = path  # type: ignore[attr-defined]
    return fn


def _fn(src: str, path: str = "shadow.py") -> SourceFragment:
    root = SourceFragment.from_source(src, path)
    fn = next(
        f
        for f in root.walk()
        if f.observed == "FunctionDef" and f.function_name() == "f"
    )
    return _tag(fn, src, path)


def test_local_assign_shadows_module_global_in_body_dig() -> None:
    """Module GLOBAL = b\"module\"; body GLOBAL = b\"local\" → dig uses local.

    Hex 6c6f63616c = \"local\"; 6d6f64756c65 = \"module\".
    """
    src = (
        'GLOBAL = b"module"\n'
        "def f(s):\n"
        '    GLOBAL = b"local"\n'
        "    return s.translate(GLOBAL)\n"
    )
    fn = _fn(src)
    ctx = FactoryBuildContext(
        filename="shadow.py",
        catalog=default_catalog(),
        name_resolver={"f": fn.node},
    )

    # Pre-walk: module seed is present (install-source free-name path).
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    global_binds = [b for b in body_ctx.temporal.bindings if b.name == "GLOBAL"]
    assert global_binds, "module GLOBAL must seed before body walk"
    seeded = global_binds[-1].value
    # Module constant folds to bytes/module string — not the formal SymbolicValue.
    assert not isinstance(seeded, SymbolicValue), seeded

    sugar = build_control_flow_body_sugar(fn, ctx)
    blob = str(sugar.constraint_formulas())
    # Local wins in the post.
    assert "6c6f63616c" in blob, f"expected local hex in dig post, got {blob}"
    assert (
        "6d6f64756c65" not in blob
    ), f"module hex must not appear after local shadow: {blob}"
    assert "call:translate" in blob


def test_formal_shadows_module_global_on_formal_binds() -> None:
    """def f(GLOBAL): ... formal binds after module seed and wins."""
    src = 'GLOBAL = b"module"\n' "def f(GLOBAL):\n" "    return GLOBAL\n"
    fn = _fn(src)
    ctx = FactoryBuildContext(
        filename="shadow.py",
        catalog=default_catalog(),
        name_resolver={"f": fn.node},
    )
    body_ctx = _ctx_with_formal_binds(fn, ctx)
    global_binds = [b for b in body_ctx.temporal.bindings if b.name == "GLOBAL"]
    assert global_binds, global_binds
    # Last bind for GLOBAL must be the formal (SymbolicValue), not module constant.
    assert isinstance(global_binds[-1].value, SymbolicValue), global_binds[-1].value

    sugar = build_control_flow_body_sugar(fn, ctx)
    blob = str(sugar.constraint_formulas())
    # Identity out == formal GLOBAL — no module bytes constant.
    assert "6d6f64756c65" not in blob, blob
    assert "out" in blob and "GLOBAL" in blob.upper() or "out" in blob


def test_unshadowed_module_global_still_seeds() -> None:
    """Control: without local shadow, module GLOBAL still digs (good twin of free-name)."""
    src = 'GLOBAL = b"module"\n' "def f(s):\n" "    return s.translate(GLOBAL)\n"
    fn = _fn(src)
    ctx = FactoryBuildContext(
        filename="shadow.py",
        catalog=default_catalog(),
        name_resolver={"f": fn.node},
    )
    sugar = build_control_flow_body_sugar(fn, ctx)
    blob = str(sugar.constraint_formulas())
    assert "6d6f64756c65" in blob, blob  # module
    assert "call:translate" in blob
