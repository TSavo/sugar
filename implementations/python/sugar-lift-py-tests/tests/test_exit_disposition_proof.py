"""ExitDispositionProof: exact None/False returns + static resolve floor.

Return theorem and lying twins stay. Manager→definition uses static imports
and SourceOracle module text only — no importlib/getattr/MRO/inspect.
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from sugar_lift_py_tests.exit_disposition_proof import (
    ExitDispositionProof,
    ExitDispositionUnproven,
    assert_no_runtime_resolve_authority,
    prove_exit_disposition_from_manager_expr,
    prove_exit_function_ast,
    resolve_definition_memento_from_manager_expr,
)


def _exit_fn(src: str) -> ast.FunctionDef:
    mod = ast.parse(textwrap.dedent(src))
    cls = next(n for n in mod.body if isinstance(n, ast.ClassDef))
    return next(
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "__exit__"
    )


def _prove_src(src: str) -> ExitDispositionProof:
    fn = _exit_fn(src)
    return prove_exit_function_ast(
        fn,
        module="testmod",
        class_name="M",
        source_cid="cid",
        filename="testmod.py",
    )


def test_truthful_implicit_none_fallthrough():
    assert _prove_src("""
        class M:
            def __exit__(self, *a):
                self.cleanup()
        """).kind == "never_suppresses"


def test_truthful_explicit_none_and_false():
    assert _prove_src("""
        class M:
            def __exit__(self, *a):
                if a[0] is None:
                    return None
                return False
        """).kind == "never_suppresses"


def test_truthful_raise_inside_exit_is_halt_not_suppress():
    assert _prove_src("""
        class M:
            def __exit__(self, *a):
                if a[0] is not None:
                    raise RuntimeError("exit failed")
        """).kind == "never_suppresses"


def test_lying_return_true():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src("""
            class M:
                def __exit__(self, *a):
                    return True
            """)


def test_lying_symbolic_return():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src("""
            class M:
                def __exit__(self, *a):
                    return a[0]
            """)


def test_lying_mixed_branch():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src("""
            class M:
                def __exit__(self, *a):
                    if a[0] is None:
                        return None
                    return True
            """)


def test_lying_swallowed_exception_then_return_true():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src("""
            class M:
                def __exit__(self, *a):
                    try:
                        self.close()
                    except Exception:
                        return True
            """)


def test_truthful_swallowed_exception_then_none():
    assert _prove_src("""
        class M:
            def __exit__(self, *a):
                try:
                    self.close()
                except Exception:
                    pass
        """).kind == "never_suppresses"


def test_lying_ambiguous_dispatch_return_call():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src("""
            class M:
                def __exit__(self, *a):
                    return self._maybe_suppress(a)
            """)


def test_no_runtime_resolve_authority_floor():
    assert_no_runtime_resolve_authority()


def test_static_resolve_np_errstate_via_source_imports():
    """Local ``import numpy as np`` + static re-export follow — not importlib."""
    import tempfile

    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    src = (
        "import numpy as np\n"
        "def A(z):\n"
        "    with np.errstate(all='ignore'):\n"
        "        z = z\n"
        "    return z\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    with_node = next(s for s in fn.body if s.kind == "With")
    mgr = with_node.items[0].context_expr
    memento = resolve_definition_memento_from_manager_expr(mgr)
    assert memento is not None, "static resolve must find errstate without importlib"
    assert memento.class_name == "errstate"
    assert "ufunc_config" in memento.filename or memento.module.endswith(
        "_ufunc_config"
    )
    proof = prove_exit_disposition_from_manager_expr(mgr)
    assert proof is not None and proof.kind == "never_suppresses"


def test_generator_contextmanager_is_deferred_not_falsely_proven():
    # option_context is `@contextmanager def option_context(...)` -- a GENERATOR
    # context manager, not a class with __exit__. This cut proves class __exit__
    # only (see module docstring: generator @contextmanager is a SEPARATE proof).
    # The static resolver reaches the def but finds no class __exit__, so it
    # DEFERS (no memento, no proof) -> the caller keeps RuntimeSelected. The
    # point of the assertion: the cut must NOT falsely prove a generator CM
    # never-suppresses just because its post-yield cleanup happens to look inert.
    import tempfile

    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    src = (
        "from pandas import option_context\n"
        "def A(z):\n"
        "    with option_context('display.max_rows', 10):\n"
        "        z = z\n"
        "    return z\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    with_node = next(s for s in fn.body if s.kind == "With")
    mgr = with_node.items[0].context_expr
    # generator CM -> class __exit__ analysis is N/A -> deferred, not proven.
    assert resolve_definition_memento_from_manager_expr(mgr) is None
    assert prove_exit_disposition_from_manager_expr(mgr) is None


def test_open_still_unproven_statically():
    import tempfile

    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    src = "def A(f):\n    with open(f):\n        pass\n    return f\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    with_node = next(s for s in fn.body if s.kind == "With")
    assert (
        prove_exit_disposition_from_manager_expr(with_node.items[0].context_expr)
        is None
    )
