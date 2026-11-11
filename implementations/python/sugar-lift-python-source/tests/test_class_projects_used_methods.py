"""A class past the call-closure bound projects the methods its instances run.

``pandas.io.pytables.HDFStore`` has 43 methods.  Projecting the class followed
every source call of every method, and theirs, and refused by name past the
closure bound (``call-closure-over-bound``) -- the nine pytables files of
#7664 stopped there.  But a class statement binds its methods and runs none of
them.  When the whole class does not fit, it is projected again over the
methods its instances run on the projected path: construction, the
context-manager protocol, and every method those name on ``self``,
transitively.  The rest keep their source bodies for whoever calls them, and
their callees are never projected here.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.class_definition_value import DeferredClassMethodV1
from sugar_lift_py_tests.sugar.deferred_method_body_sugar import DeferredMethodBodySugar
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_python_source.manager_construction import (
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
)
from sugar_lift_python_source.resolution_session import (
    SOURCE_CALL_CLOSURE_FRAME_BOUND,
)

from test_call_target_gap_mechanisms import _call_chain, _construct


def _chain_modules():
    """``step1`` reaches one definition more than the bound, one per module."""
    _manager, modules = _call_chain(SOURCE_CALL_CLOSURE_FRAME_BOUND)
    return modules


def _guard(*, enter: str) -> str:
    return (
        "from arbitrary.link1 import step1\n"
        "\n"
        "class make_guard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        f"        return {enter}\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        "    def far(self):\n"
        "        return step1(self.expected)\n"
    )


def test_unused_method_past_the_bound_does_not_refuse_the_class(tmp_path):
    result = _construct(tmp_path, _guard(enter="self"), **_chain_modules())

    assert isinstance(result, ConstructedManagerBehaviorV1), result
    # ``far`` is bound but not on the projected path: its body is kept for a
    # caller, never constructed here.
    methods = {method.name: method for method in result.receiver_state.defining_class.methods}
    assert isinstance(methods["far"], DeferredClassMethodV1)
    assert methods["far"].unprojected
    assert not isinstance(methods["__enter__"], DeferredClassMethodV1)
    # The instance still names ``far``; running it refuses by name.
    (bound,) = [m for m in result.receiver_state.methods if m.name == "far"]
    assert isinstance(bound.body, DeferredMethodBodySugar)
    with pytest.raises(SugarNotWritten, match="was not constructed on this path"):
        bound.body.desugar()


def test_used_method_past_the_bound_still_refuses(tmp_path):
    # The lying twin: when ``__enter__`` runs ``far``, the over-bound closure
    # IS on the projected path, and the class is refused by name as before.
    result = _construct(tmp_path, _guard(enter="self.far()"), **_chain_modules())

    assert isinstance(result, ManagerConstructionGapV1), result
    assert result.kind == "call-closure-over-bound"
    assert "narrowed to the methods its instances run" in result.detail


# #7733: ``read_csv`` is a FUNCTION that reaches ``TextFileReader``, a class of
# its own module, whose ``read`` reaches ``Series`` and hundreds more.  The
# function runs ``TextFileReader(...)``; it runs none of its unused methods.
# The narrowing is the class's, wherever the class is reached from.


def _factory_over(guard_source: str) -> str:
    return guard_source.replace("class make_guard:", "class Guard:") + (
        "\n"
        "def make_guard(expected):\n"
        "    return Guard(expected)\n"
    )


def test_function_reaching_a_same_module_class_projects_only_used_methods(tmp_path):
    result = _construct(
        tmp_path, _factory_over(_guard(enter="self")), **_chain_modules()
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result
    methods = {
        method.name: method for method in result.receiver_state.defining_class.methods
    }
    assert isinstance(methods["far"], DeferredClassMethodV1)
    assert methods["far"].unprojected
    assert not isinstance(methods["__enter__"], DeferredClassMethodV1)


def test_function_whose_class_runs_the_far_method_still_refuses(tmp_path):
    # Lying twin: ``__enter__`` runs ``far``; narrowing cannot drop it.
    result = _construct(
        tmp_path, _factory_over(_guard(enter="self.far()")), **_chain_modules()
    )

    assert isinstance(result, ManagerConstructionGapV1), result
    assert result.kind == "call-closure-over-bound"
    assert "narrowed to the methods its instances run" in result.detail


def test_class_reached_as_a_callee_in_another_module_is_narrowed(tmp_path):
    guards = _factory_over(_guard(enter="self")).split("\ndef make_guard")[0]
    manager = (
        "from arbitrary.guards import Guard\n"
        "\n"
        "def make_guard(expected):\n"
        "    return Guard(expected)\n"
    )
    result = _construct(tmp_path, manager, guards=guards, **_chain_modules())

    assert isinstance(result, ConstructedManagerBehaviorV1), result
    methods = {
        method.name: method for method in result.receiver_state.defining_class.methods
    }
    assert isinstance(methods["far"], DeferredClassMethodV1)
    assert methods["far"].unprojected


def test_class_reached_as_a_callee_that_runs_the_far_method_still_refuses(tmp_path):
    # Lying twin of the callee arm.
    guards = _factory_over(_guard(enter="self.far()")).split("\ndef make_guard")[0]
    manager = (
        "from arbitrary.guards import Guard\n"
        "\n"
        "def make_guard(expected):\n"
        "    return Guard(expected)\n"
    )
    result = _construct(tmp_path, manager, guards=guards, **_chain_modules())

    assert isinstance(result, ManagerConstructionGapV1), result
    assert result.kind == "call-closure-over-bound"
