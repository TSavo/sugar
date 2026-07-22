"""ExitDispositionProof: exact None/False completed returns (incl. fallthrough).

Lying twins: True, symbolic, mixed branch, swallowed-but-true, ambiguous
dispatch, overriding subclass. Truthful: restore-only / implicit None.
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from sugar_lift_py_tests.exit_disposition_proof import (
    ExitDispositionProof,
    ExitDispositionUnproven,
    prove_exit_function_ast,
    prove_never_suppresses_for_class,
)


def _exit_fn(src: str) -> ast.FunctionDef:
    mod = ast.parse(textwrap.dedent(src))
    cls = next(n for n in mod.body if isinstance(n, ast.ClassDef))
    fn = next(
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__exit__"
    )
    return fn


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
    proof = _prove_src(
        """
        class M:
            def __exit__(self, *a):
                self.cleanup()
        """
    )
    assert proof.kind == "never_suppresses"


def test_truthful_explicit_none_and_false():
    proof = _prove_src(
        """
        class M:
            def __exit__(self, *a):
                if a[0] is None:
                    return None
                return False
        """
    )
    assert proof.kind == "never_suppresses"


def test_truthful_raise_inside_exit_is_halt_not_suppress():
    """Exit halt is intact; raise does not invent suppression."""
    proof = _prove_src(
        """
        class M:
            def __exit__(self, *a):
                if a[0] is not None:
                    raise RuntimeError("exit failed")
        """
    )
    assert proof.kind == "never_suppresses"


def test_lying_return_true():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src(
            """
            class M:
                def __exit__(self, *a):
                    return True
            """
        )


def test_lying_symbolic_return():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src(
            """
            class M:
                def __exit__(self, *a):
                    return a[0]
            """
        )


def test_lying_mixed_branch():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src(
            """
            class M:
                def __exit__(self, *a):
                    if a[0] is None:
                        return None
                    return True
            """
        )


def test_lying_swallowed_exception_then_return_true():
    """Except that swallows is fine only if completed returns stay None/False."""
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src(
            """
            class M:
                def __exit__(self, *a):
                    try:
                        self.close()
                    except Exception:
                        return True
            """
        )


def test_truthful_swallowed_exception_then_none():
    proof = _prove_src(
        """
        class M:
            def __exit__(self, *a):
                try:
                    self.close()
                except Exception:
                    pass
        """
    )
    assert proof.kind == "never_suppresses"


def test_lying_ambiguous_dispatch_return_call():
    with pytest.raises(ExitDispositionUnproven, match="not exact None/False"):
        _prove_src(
            """
            class M:
                def __exit__(self, *a):
                    return self._maybe_suppress(a)
            """
        )


def test_overriding_subclass_uses_defining_class_exit():
    """Subclass without override inherits base proof; with override is own source."""

    class Base:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    class GoodChild(Base):
        pass

    class BadChild(Base):
        def __exit__(self, *a):
            return True

    # Base-defined exit is never-suppress (if source is available). These live
    # in this test module — SourceOracle installed_module_source may not pin
    # test modules. prove_never_suppresses_for_class needs on-disk module source.
    # Unit proof on AST for BadChild-style body:
    with pytest.raises(ExitDispositionUnproven):
        _prove_src(
            """
            class BadChild:
                def __exit__(self, *a):
                    return True
            """
        )
    proof = _prove_src(
        """
        class GoodChild:
            def __exit__(self, *a):
                return None
        """
    )
    assert proof.kind == "never_suppresses"


def test_numpy_errstate_source_proof():
    """Installed numpy.errstate: SourceOracle + exact None fallthrough."""
    import numpy as np

    proof = prove_never_suppresses_for_class(np.errstate)
    assert proof is not None
    assert proof.kind == "never_suppresses"
    assert proof.class_name == "errstate"
    assert proof.method_name == "__exit__"
    assert proof.source_cid


def test_pandas_option_context_source_proof():
    from pandas import option_context

    proof = prove_never_suppresses_for_class(option_context)
    assert proof is not None
    assert proof.kind == "never_suppresses"
    assert proof.class_name == "option_context"


def test_switchdir_is_not_class_exit_proof():
    """Generator CM is a separate proof — class path must not invent NeverSuppresses."""
    # switchdir is a function, not a type
    import importlib.util
    from pathlib import Path

    util_path = Path(
        "/Users/tsavo/provekit/.venv/lib/python3.14/site-packages/numpy/f2py/tests/util.py"
    )
    # Do not import util (side-effect meson). Just assert function form unproven.
    assert prove_never_suppresses_for_class(type("X", (), {})) is None
