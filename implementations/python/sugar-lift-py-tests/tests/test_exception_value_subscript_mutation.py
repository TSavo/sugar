import pytest

from sugar_lift_py_tests.floor import ExceptionValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "exception_value_subscript_mutation.py"
    path.write_text(
        "def f(exc, replacement):\n    exc[0] = replacement\n    del exc[0]\n"
        "    exc[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment, body[2].fragment


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setitem", "ExceptionValue.setitem", 0),
        ("delitem", "ExceptionValue.delitem", 1),
    ),
)
def test_exception_value_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = ExceptionValue("ValueError", (), site)
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_exception_value_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site, _read_site = _sites(tmp_path)
    value = ExceptionValue("ValueError", (), store_site)
    store = value.setitem(TermValue(0), TermValue(7), store_site, None)
    delete = value.delitem(TermValue(0), delete_site, None)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)


def test_exception_value_subscript_read_is_a_ground_type_error(tmp_path):
    """``exc[0]`` raises TypeError: no builtin exception defines __getitem__.

    The exit is decided, so it is a RaiseEffect with its class identity (which
    ``except`` and a With's ``__exit__`` consume), not a RuntimeEffect.
    """
    import builtins

    from sugar_lift_py_tests.effect import RaiseEffect, RuntimeEffect

    assert not [
        name
        for name, value in vars(builtins).items()
        if isinstance(value, type)
        and issubclass(value, BaseException)
        and hasattr(value, "__getitem__")
    ]
    read_site = _sites(tmp_path)[2]
    outcome = ExceptionValue("ValueError", (), read_site).subscript(
        TermValue(0), read_site
    )
    effect = outcome.value.effect
    assert isinstance(effect, RaiseEffect)
    assert not isinstance(effect, RuntimeEffect)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == "ExceptionValue.subscript"
    assert effect.occurrence_id == str(read_site)
