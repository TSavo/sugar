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
