"""RED: enum's source metaclass return is projected before publication."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_python_source.manager_construction import (
    _project_metaclass_final_class,
)
from sugar_lift_py_tests.floor import BlockValue, TermValue
from sugar_lift_py_tests.floor.decorated_class_value import (
    _metaclass_publication_cids,
)
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.raise_value import RaiseValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.source_return_projection import (
    project_authenticated_source_return,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_source_tree.panic import SugarNotWritten


def test_module_metaclass_publication_projects_completed_final_class() -> None:
    returned = TermValue(17)
    body = BlockValue(
        (ReturnValue(returned),), fall_through=(false_guard(),), can_fall_through=False
    )

    assert _project_metaclass_final_class(body, blame="enum.py:712") is returned


def test_source_return_projection_selects_one_unconditional_returned_floor() -> None:
    returned = TermValue("authenticated-class")
    body = BlockValue(
        (ReturnValue(returned),), fall_through=(false_guard(),), can_fall_through=False
    )

    assert project_authenticated_source_return(body) is returned


@pytest.mark.parametrize(
    "ambiguous",
    (
        BlockValue(
            (ReturnValue(TermValue("first")), ReturnValue(TermValue("second"))),
            can_fall_through=False,
        ),
        BlockValue(
            (ReturnValue(TermValue("returned")),),
            fall_through=(true_guard(),),
            can_fall_through=True,
        ),
        BlockValue(
            (ReturnValue(TermValue("returned")),),
            can_fall_through=True,
        ),
        BlockValue(
            (
                ReturnValue(TermValue("returned")),
                RaiseValue(RaiseEffect(exception_name="RuntimeError")),
            ),
            can_fall_through=False,
        ),
        BlockValue(
            (GuardedReturn((make_var("undecided"),), TermValue("guarded")),),
            can_fall_through=False,
        ),
    ),
    ids=(
        "two-returns",
        "fall-through-guard",
        "fall-through-capability",
        "raise-arm",
        "undecided-guard",
    ),
)
def test_source_return_projection_preserves_ambiguous_control_flow(ambiguous) -> None:
    assert project_authenticated_source_return(ambiguous) is ambiguous


@pytest.mark.parametrize(
    "lying_final",
    (
        BlockValue((TermValue("foreign"),)),
        BlockValue(
            (RaiseValue(RaiseEffect(exception_name="RuntimeError")),),
            can_fall_through=False,
        ),
    ),
)
def test_raw_block_final_class_controls_remain_loud(lying_final) -> None:
    with pytest.raises(SugarNotWritten, match="no unique authenticated returned class"):
        _project_metaclass_final_class(lying_final, blame="enum.py:712")


def test_metaclass_projection_gap_names_the_retained_control_shape() -> None:
    guarded = GuardedReturn((make_var("undecided"),), TermValue("candidate"))
    body = BlockValue(
        (TermValue("testimony"), guarded),
        fall_through=(make_var("fallthrough"),),
        can_fall_through=True,
    )

    with pytest.raises(SugarNotWritten) as caught:
        _project_metaclass_final_class(body, blame="enum.py:1081:21")

    assert (
        "shape=BlockValue[TermValue,GuardedReturn<TermValue>[guards=1]]; "
        "canFallThrough=True; fallThroughGuards=1"
    ) in str(caught.value)


@dataclass(frozen=True)
class _Coordinate:
    name: str

    def wire(self):
        return {"name": self.name}


def test_metaclass_publication_identity_separates_returned_floor_and_call_site() -> None:
    shared = dict(
        source_cid="source-cid",
        definition=_Coordinate("definition"),
        binding_occurrence=_Coordinate("binding"),
        raw_class=TermValue(1),
        metaclass_floor=TermValue(2),
        metaclass_callable=TermValue(3),
        class_name_floor=TermValue(4),
        bases_floor=TermValue(5),
        namespace_floor=TermValue(6),
        module_construction_receipt_cid="receipt-cid",
    )
    first_application, first_publication = _metaclass_publication_cids(
        **shared,
        metaclass_occurrence=_Coordinate("call:first"),
        final_class=TermValue(7),
    )
    changed_result, changed_result_publication = _metaclass_publication_cids(
        **shared,
        metaclass_occurrence=_Coordinate("call:first"),
        final_class=TermValue(8),
    )
    changed_call, _ = _metaclass_publication_cids(
        **shared,
        metaclass_occurrence=_Coordinate("call:second"),
        final_class=TermValue(7),
    )

    assert changed_result != first_application
    assert changed_result_publication != first_publication
    assert changed_call != first_application
