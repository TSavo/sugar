from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import NoneValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.delete_effect_sugar import SubscriptDeleteEffectSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "none_subscript_mutation.py"
    path.write_text("def f(obj, value):\n    obj[0] = value\n    del obj[0]\n")
    body = next(SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()).body
    return body[0].fragment, body[1].fragment


@dataclass(frozen=True)
class _Value(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    store = SubscriptStoreEffectSugar(_Value(NoneValue()), _Value(TermValue(0)), _Value(TermValue(7)), store_site).desugar()
    delete = SubscriptDeleteEffectSugar(_Value(NoneValue()), _Value(TermValue(0)), delete_site).desugar()
    return ((store, "NoneValue.setitem", store_site), (delete, "NoneValue.delitem", delete_site))


def test_none_subscript_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        assert isinstance(outcome, Incomplete)
        assert outcome.effect.exception_name == "TypeError"
        assert outcome.effect.producer_node_owner == owner
        assert outcome.effect.occurrence_id == str(site)


def test_none_subscript_mutations_cannot_fabricate_completion(tmp_path):
    for outcome, _, _ in _outcomes(tmp_path):
        assert not isinstance(outcome, Complete)
