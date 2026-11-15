import pytest

from sugar_lift_py_tests.floor import SliceValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "slice_value_subscript_mutation.py"
    path.write_text(
        "def f(value, replacement):\n    value[0] = replacement\n    del value[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _only_halt(outcome):
    """The outcome is one unconditional halt and nothing else: its effect."""
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.exits
    return halt.effect


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (("setitem", "SliceValue.setitem", 0), ("delitem", "SliceValue.delitem", 1)),
)
def test_slice_value_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = SliceValue(None, None, None)
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    effect = _only_halt(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_slice_value_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = SliceValue(None, None, None)
    store = value.setitem(TermValue(0), TermValue(7), store_site, None)
    delete = value.delitem(TermValue(0), delete_site, None)
    assert _only_halt(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _only_halt(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"
