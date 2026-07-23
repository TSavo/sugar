"""Resource `with` under RuntimeSelected (#5994 step 4).

Production: unenrolled managers stay LOUD as ``RuntimeSelectedContextManager``.
Tree synthesizes ManagerRef + parametric exit; enter/exit ExitSet lives on
``WithResourceSugar`` (unit twins). No manager is admitted green without
constructed enter/exit or explicit red.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from with_resolution_fixture import source_file_with_preconstruction


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def test_resource_open_is_runtime_selected_named_residual():
    """`with open(f): ...` is loud, distinctly named — not dissolved."""
    with pytest.raises(SugarNotWritten) as ei:
        _fn("def A(f):\n    with open(f):\n        pass\n    return f\n").sugar()
    panic = ei.value
    assert isinstance(panic, SugarNotWritten)
    assert type(panic).__name__ == "ContextManagerResolutionConstructionGap"
    assert panic.kind == "runtime-selected"


def test_resource_open_is_not_silent_dissolve():
    with pytest.raises(SugarNotWritten):
        sugar = _fn(
            "def A(f):\n    with open(f):\n        x = 1\n    return f\n"
        ).sugar()
        sugar.desugar()


def test_resource_named_residual_distinct_from_bare_sugar_not_written():
    with pytest.raises(SugarNotWritten) as ei:
        _fn("def A(z):\n    with open(z):\n        pass\n    return z\n").sugar()
    assert type(ei.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert issubclass(type(ei.value), SugarNotWritten)


def test_assertion_manager_without_provider_contract_is_typed_loud():
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "def A(z):\n    with pytest.raises(ValueError):\n        raise ValueError\n"
            "    return z\n"
        ).sugar()
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"


def test_suppress_manager_without_provider_contract_is_typed_loud():
    with pytest.raises(SugarNotWritten) as caught:
        _fn(
            "def A(z):\n    with contextlib.suppress(KeyError):\n        raise KeyError\n"
            "    return z\n"
        ).sugar()
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"


def test_with_item_parametric_exit_uses_manager_ref_and_exit_refs():
    """One exit call: M.__exit__(ExitTypeRef(X), ExitValueRef(X), ExitTracebackRef(X))."""
    fn = _fn("def A(m):\n    with m:\n        pass\n    return m\n")
    with_node = next(s for s in fn.body if s.kind == "With")
    item = with_node.items[0]
    mgr_slot = item._manager_slot_id()
    face_id = item._exit_face_id()
    assert face_id == f"{mgr_slot}#exit_face"

    ref = item._make_manager_ref()
    assert ref.kind == "ManagerRef"
    assert ref.slot_id == mgr_slot

    enter = item._make_enter_call()
    assert enter.func.attr == "__enter__"
    assert enter.func.value.kind == "ManagerRef"
    assert enter.func.value.slot_id == mgr_slot

    exit_ = item._make_parametric_exit_call()
    assert exit_.func.attr == "__exit__"
    assert exit_.func.value.kind == "ManagerRef"
    assert exit_.func.value.slot_id == mgr_slot
    assert len(exit_.args) == 3
    assert exit_.args[0].kind == "ExitTypeRef"
    assert exit_.args[1].kind == "ExitValueRef"
    assert exit_.args[2].kind == "ExitTracebackRef"
    assert exit_.args[0].face_id == face_id
    assert exit_.args[1].face_id == face_id
    assert exit_.args[2].face_id == face_id

    exit_sugar = exit_.sugar()
    assert type(exit_sugar).__name__ == "MethodCallSugar"
    assert exit_sugar.name == "__exit__"
    assert type(exit_sugar.receiver).__name__ == "ManagerRefSugar"
    assert [type(a).__name__ for a in exit_sugar.args] == [
        "ExitTypeRefSugar",
        "ExitValueRefSugar",
        "ExitTracebackRefSugar",
    ]


if __name__ == "__main__":
    test_resource_open_is_runtime_selected_named_residual()
    test_resource_open_is_not_silent_dissolve()
    test_resource_named_residual_distinct_from_bare_sugar_not_written()
    test_assertion_manager_pytest_raises_still_lifts()
    test_suppress_manager_still_lifts()
    test_with_item_parametric_exit_uses_manager_ref_and_exit_refs()
    print("ok: resource with RuntimeSelected; parametric exit tree coords")
