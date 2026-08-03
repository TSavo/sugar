from sugar_lift_py_tests.floor import ComplexValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "complex_attribute_mutation.py"
    path.write_text("def f(obj, value):\n    obj.attr = value\n    del obj.attr\n")
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = ComplexValue(1.0, 2.0)
    return (
        (
            value.setattr("attr", TermValue(7), store_site),
            "ComplexValue.setattr",
            store_site,
        ),
        (value.delattr("attr", delete_site), "ComplexValue.delattr", delete_site),
    )


def test_complex_attribute_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        assert outcome.value.effect.exception_name == "AttributeError"
        assert outcome.value.effect.producer_node_owner == owner
        assert outcome.value.effect.occurrence_id == str(site)


def test_complex_attribute_mutations_reject_completion_and_wrong_site(tmp_path):
    outcomes = _outcomes(tmp_path)
    store, _, store_site = outcomes[0]
    delete, _, delete_site = outcomes[1]
    assert store_site != delete_site
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)
