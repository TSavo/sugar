from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, make_var


def test_symbolic_support_keeps_one_identity_under_a_guard() -> None:
    value = SymbolicValue(make_var("value"))
    guarded = value.guarded(atomic("path", []))

    assert guarded is value
    assert guarded.to_term(owner="test") == make_var("value")


def test_guard_does_not_become_symbolic_value_content_identity() -> None:
    value = SymbolicValue(make_var("value"))

    assert value.guarded(atomic("left", [])) is value.guarded(atomic("right", []))
    assert value.inv_contribution() == ()
    assert value.post_contribution() == ()


def test_symbolic_name_attribute_is_a_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    value = SymbolicValue(make_var("expected"))
    site = "symbolic-name-attr"
    outcome = value.attribute("__name__", site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "__name__"
    assert outcome.value.term == ctor(
        "attr:__name__",
        [value.to_term(owner=str(site))],
        symbol_kind="method-coordinate",
    )


def test_symbolic_unknown_attribute_stays_undecided() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    value = SymbolicValue(make_var("expected"))
    try:
        value.attribute("not_a_data_model_name", "symbolic-unknown-attr")
    except SugarNotWritten as exc:
        assert exc.owner == "SymbolicValue.attribute"
        assert "not_a_data_model_name" in (exc.observed or "")
    else:
        raise AssertionError("expected SymbolicValue.attribute to stay undecided")


def test_call_site_name_attribute_is_a_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    receiver = CallSiteValue(
        target_name="__getitem__",
        arg_values=(SymbolicValue(make_var("xs")),),
        parameters=(),
        term=ctor(
            "py.subscript",
            [SymbolicValue(make_var("xs")).to_term(owner="callsite-name")],
            symbol_kind="coordinate",
        ),
        body=None,
        site="callsite-name",
    )
    site = "callsite-name-attr"
    outcome = receiver.attribute("__name__", site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "__name__"
    assert outcome.value.term == ctor(
        "attr:__name__",
        [receiver.to_term(owner=str(site))],
        symbol_kind="method-coordinate",
    )


def test_joined_str_names_unground_interpolation_as_an_fstring_coordinate(
    tmp_path,
) -> None:
    from pathlib import Path

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
    from sugar_source_tree.tree import SourceFile

    path = Path(tmp_path) / "diag.py"
    path.write_text(
        'result = f"DID NOT RAISE {unknown.__name__}"\n',
        encoding="utf-8",
    )
    tree = SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    joined = next(node for node in tree.nodes() if node.kind == "JoinedStr")
    ctx = ReduceContext.root(owner="fstring-diag").with_temporal(
        builtin_name_temporal()
    )
    outcome = joined.sugar().desugar(ctx)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert getattr(outcome.value.term, "name", None) == "python:fstring"
