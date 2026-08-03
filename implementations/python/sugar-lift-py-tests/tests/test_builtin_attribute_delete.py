from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import ListValue, NoneValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.delete_effect_sugar import AttributeDeleteEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _site(tmp_path):
    path = tmp_path / "builtin_attr_delete.py"
    path.write_text("def f(obj):\n    del obj.attr\n")
    return (
        next(
            SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
        )
        .body[0]
        .fragment
    )


@dataclass(frozen=True)
class _Receiver(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


@pytest.mark.parametrize(
    ("receiver", "owner"),
    ((ListValue(()), "ListValue.delattr"), (NoneValue(), "NoneValue.delattr")),
)
def test_builtin_without_instance_dict_delete_has_exact_owner_occurrence(
    tmp_path, receiver, owner
):
    site = _site(tmp_path)
    outcome = AttributeDeleteEffectSugar(_Receiver(receiver), "attr", site).desugar()
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "AttributeError"
    assert outcome.effect.producer_node_owner == owner
    assert outcome.effect.occurrence_id == str(site)


@pytest.mark.parametrize("receiver", (ListValue(()), NoneValue()))
def test_builtin_without_instance_dict_delete_cannot_fabricate_completion(
    tmp_path, receiver
):
    outcome = AttributeDeleteEffectSugar(
        _Receiver(receiver), "attr", _site(tmp_path)
    ).desugar()
    assert not isinstance(outcome, Complete)
