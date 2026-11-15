from sugar_lift_py_tests.floor import ComplexValue, TermValue
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "complex_attribute_mutation.py"
    path.write_text("def f(obj, value):\n    obj.attr = value\n    del obj.attr\n")
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _raised(outcome):
    """The effect of the mutation's one exit: a halted arm, never a completion."""
    (exit_,) = outcome.exits
    assert isinstance(exit_, Halted)
    return exit_.effect


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = ComplexValue(1.0, 2.0)
    return (
        (
            value.setattr("attr", TermValue(7), store_site, None),
            "ComplexValue.setattr",
            store_site,
        ),
        (
            value.delattr("attr", delete_site, None),
            "ComplexValue.delattr",
            delete_site,
        ),
    )


def test_complex_attribute_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        effect = _raised(outcome)
        assert effect.exception_name == "AttributeError"
        assert effect.producer_node_owner == owner
        assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_complex_attribute_mutations_reject_completion_and_wrong_site(tmp_path):
    outcomes = _outcomes(tmp_path)
    store, _, store_site = outcomes[0]
    delete, _, delete_site = outcomes[1]
    assert store_site != delete_site
    store_effect = _raised(store)
    delete_effect = _raised(delete)
    assert store_effect.occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert delete_effect.occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"
