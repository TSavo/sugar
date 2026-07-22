"""Resource `with` under RuntimeSelected (#5994 step 4).

Production: unenrolled managers (``open``, …) stay LOUD as the named residual
``RuntimeSelectedContextManager`` until enter/exit are constructed. The
enter/exit ExitSet transformation lives on ``WithResourceSugar`` (unit twins
in ``test_with_resource_sugar.py``); assertion managers (Expects/Suppresses)
stay on ``WithContractSugar``. No manager is admitted green without constructed
enter/exit or an explicit red residual.
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


def test_with_item_synthesizes_enter_exit_method_coordinates():
    """Tree owns ``manager.__enter__()`` / ``__exit__(None,None,None)`` coords.

    Production open still RuntimeSelected; synthesis is the door for a future
    typed disposition — not a callback injection site.
    """
    fn = _fn("def A(m):\n    with m:\n        pass\n    return m\n")
    with_node = next(s for s in fn.body if s.kind == "With")
    item = with_node.items[0]
    enter = item._make_enter_call()
    exit_ = item._make_exit_call()
    assert enter.kind == "Call"
    assert enter.func.kind == "Attribute"
    assert enter.func.attr == "__enter__"
    assert enter.args == ()
    assert exit_.kind == "Call"
    assert exit_.func.kind == "Attribute"
    assert exit_.func.attr == "__exit__"
    assert len(exit_.args) == 3
    # Method coords sugar through the normal Call/Attribute door.
    enter_sugar = enter.sugar()
    exit_sugar = exit_.sugar()
    assert type(enter_sugar).__name__ == "MethodCallSugar"
    assert type(exit_sugar).__name__ == "MethodCallSugar"
    assert enter_sugar.name == "__enter__"
    assert exit_sugar.name == "__exit__"


if __name__ == "__main__":
    test_resource_open_is_runtime_selected_named_residual()
    test_resource_open_is_not_silent_dissolve()
    test_resource_named_residual_distinct_from_bare_sugar_not_written()
    test_assertion_manager_pytest_raises_still_lifts()
    test_suppress_manager_still_lifts()
    test_with_item_synthesizes_enter_exit_method_coordinates()
    print("ok: resource with is RuntimeSelected named residual; Expects undisturbed")
