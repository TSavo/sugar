from dataclasses import dataclass

from sugar_lift_py_tests.floor import DictValue, TermValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.delete_effect_sugar import AttributeDeleteEffectSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "dict_attribute_mutation.py"
    path.write_text("def f(obj, value):\n    obj.attr = value\n    del obj.attr\n")
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


@dataclass(frozen=True)
class _Value(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    receiver = DictValue(())
    store = AttributeStoreEffectSugar(
        _Value(receiver), _Value(TermValue(7)), "attr", store_site
    ).desugar()
    delete = AttributeDeleteEffectSugar(_Value(receiver), "attr", delete_site).desugar()
    return (
        (store, "DictValue.setattr", store_site),
        (delete, "DictValue.delattr", delete_site),
    )


def test_dict_attribute_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
        (halt,) = outcome.halts()
        assert halt.effect.exception_name == "AttributeError"
        assert halt.effect.producer_node_owner == owner
        assert halt.effect.occurrence_id == str(site)


def test_dict_attribute_mutations_cannot_fabricate_completion(tmp_path):
    for outcome, _, _ in _outcomes(tmp_path):
        assert outcome.completed_value() is None


def test_dict_attribute_mutations_reject_wrong_site_substitution(tmp_path):
    outcomes = _outcomes(tmp_path)
    store_outcome, _, store_site = outcomes[0]
    delete_outcome, _, delete_site = outcomes[1]
    (store_halt,) = store_outcome.exits
    (delete_halt,) = delete_outcome.exits

    assert store_site != delete_site
    assert store_halt.effect.occurrence_id == str(store_site)
    assert store_halt.effect.occurrence_id != str(delete_site)
    assert delete_halt.effect.occurrence_id == str(delete_site)
    assert delete_halt.effect.occurrence_id != str(store_site)
