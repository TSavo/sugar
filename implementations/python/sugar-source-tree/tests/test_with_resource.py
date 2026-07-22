"""Resource `with` under RuntimeSelected (#5994 step 4).

Honest v1: we never lift ``__enter__``/``__exit__``, so no resource manager
is proven ``NeverSuppresses``. Every unenrolled resource manager is therefore
``RuntimeSelected`` and stays LOUD as the named residual
``RuntimeSelectedContextManager`` — not a silent dissolve, not a bare
``SugarNotWritten``, not a false green. Assertion managers (Expects/Suppresses
via the membrane) keep their wired path.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import (
    RuntimeSelectedContextManager,
    SugarNotWritten,
)
from sugar_source_tree.tree import SourceFile


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _val(src: str):
    return _fn(src).sugar().desugar().value


def test_resource_open_is_runtime_selected_named_residual():
    """`with open(f): ...` is loud, distinctly named — not dissolved."""
    with pytest.raises(RuntimeSelectedContextManager) as ei:
        _fn("def A(f):\n    with open(f):\n        pass\n    return f\n").sugar()
    panic = ei.value
    assert isinstance(panic, SugarNotWritten)  # still a gap for census
    assert type(panic) is RuntimeSelectedContextManager  # not bare
    assert "unauthenticated context manager — exit suppression runtime-selected" in (
        panic.observed
    )
    assert panic.owner == "With.sugar"


def test_resource_open_is_not_silent_dissolve():
    """No sugar object, no enter/exit splice: the throw is the residual."""
    with pytest.raises(RuntimeSelectedContextManager):
        sugar = _fn(
            "def A(f):\n    with open(f):\n        x = 1\n    return f\n"
        ).sugar()
        # If sugar() ever returned instead of raising, that would be a dissolve.
        sugar.desugar()


def test_resource_named_residual_distinct_from_bare_sugar_not_written():
    """Census discrimination: resource managers are a typed subclass."""
    with pytest.raises(RuntimeSelectedContextManager) as ei:
        _fn("def A(z):\n    with open(z):\n        pass\n    return z\n").sugar()
    assert type(ei.value) is not SugarNotWritten
    assert issubclass(type(ei.value), SugarNotWritten)


def test_assertion_manager_pytest_raises_still_lifts():
    """Step-4 residual must not disturb the Expects path."""
    v = _val(
        "def A(z):\n    with pytest.raises(ValueError):\n        raise ValueError\n"
        "    return z\n"
    )
    inv = v.invs()[0]
    assert inv.name == "="
    assert inv.args[0].value == inv.args[1].value == "ValueError"
    assert v.post().args[1].name == "z"


def test_suppress_manager_still_lifts():
    v = _val(
        "def A(z):\n    with contextlib.suppress(KeyError):\n        raise KeyError\n"
        "    return z\n"
    )
    assert v.invs() == () and v.post().args[1].name == "z"


if __name__ == "__main__":
    test_resource_open_is_runtime_selected_named_residual()
    test_resource_open_is_not_silent_dissolve()
    test_resource_named_residual_distinct_from_bare_sugar_not_written()
    test_assertion_manager_pytest_raises_still_lifts()
    test_suppress_manager_still_lifts()
    print("ok: resource with is RuntimeSelected named residual; Expects undisturbed")
