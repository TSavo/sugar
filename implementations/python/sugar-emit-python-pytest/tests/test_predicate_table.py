"""Unit tests for the inline predicate -> pytest assertion mapping."""

from __future__ import annotations

from sugar_emit_python_pytest import predicate_table as pt


def _op(name: str, *args: dict) -> dict:
    return {"kind": "op", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def _const(value) -> dict:
    return {"kind": "const", "value": value}


def test_eq_renders_double_equals() -> None:
    assert pt.render(_op("concept:eq", _var("a"), _var("b"))) == "assert a == b"


def test_ne_renders_not_equals() -> None:
    assert pt.render(_op("concept:ne", _var("a"), _var("b"))) == "assert a != b"


def test_ordering_operators() -> None:
    assert pt.render(_op("concept:lt", _var("a"), _var("b"))) == "assert a < b"
    assert pt.render(_op("concept:gt", _var("a"), _var("b"))) == "assert a > b"
    assert pt.render(_op("concept:le", _var("a"), _var("b"))) == "assert a <= b"
    assert pt.render(_op("concept:ge", _var("a"), _var("b"))) == "assert a >= b"


def test_option_is_some_renders_is_not_none() -> None:
    assert pt.render(_op("concept:option-is-some", _var("x"))) == "assert x is not None"


def test_option_is_none_renders_is_none() -> None:
    assert pt.render(_op("concept:option-is-none", _var("x"))) == "assert x is None"


def test_fallible_err_renders_pytest_raises_block() -> None:
    rendered = pt.render(_op("concept:fallible-err", _var("f")))
    assert rendered is not None
    assert rendered.startswith("with pytest.raises(Exception):")
    assert "f()" in rendered


def test_const_args_render_python_literals() -> None:
    assert pt.render(_op("concept:eq", _var("a"), _const(7))) == "assert a == 7"
    assert pt.render(_op("concept:eq", _var("a"), _const("hi"))) == "assert a == 'hi'"
    assert (
        pt.render(_op("concept:option-is-none", _const(None))) == "assert None is None"
    )


def test_arithmetic_subtree_renders_infix() -> None:
    expr = _op("+", _var("a"), _var("b"))
    assert pt.render(_op("concept:eq", _var("c"), expr)) == "assert c == (a + b)"


def test_call_subtree_renders_application() -> None:
    call = _op("clamp", _var("x"))
    assert pt.render(_op("concept:eq", _var("y"), call)) == "assert y == clamp(x)"


def test_bare_name_form_accepted() -> None:
    # Harvester's internal kind:"atomic"/bare-name form.
    assert pt.render(
        {"kind": "atomic", "name": "eq", "args": [_var("a"), _var("b")]}
    ) == ("assert a == b")


def test_unsupported_predicate_returns_none() -> None:
    assert pt.render(_op("concept:mystery", _var("a"))) is None


def test_wrong_arity_returns_none() -> None:
    assert pt.render(_op("concept:eq", _var("a"))) is None
    assert pt.render(_op("concept:option-is-some", _var("a"), _var("b"))) is None


def test_malformed_term_returns_none() -> None:
    # A var with no name cannot be rendered, so the whole predicate refuses.
    assert pt.render(_op("concept:eq", {"kind": "var"}, _var("b"))) is None


def test_head_of_strips_concept_prefix() -> None:
    assert pt.head_of(_op("concept:eq", _var("a"), _var("b"))) == "eq"
    assert pt.head_of({"kind": "atomic", "name": "lt"}) == "lt"
    assert pt.head_of({"kind": "op"}) is None


def test_supports_reflects_table() -> None:
    assert pt.supports("eq")
    assert pt.supports("option-is-some")
    assert pt.supports("fallible-err")
    assert not pt.supports("mystery")
    assert not pt.supports(None)


def test_supported_predicates_list_is_catalog_form() -> None:
    preds = pt.supported_predicates()
    assert "concept:eq" in preds
    assert "concept:option-is-some" in preds
    assert "concept:fallible-err" in preds
    assert all(p.startswith("concept:") for p in preds)


def test_free_vars_encounter_order_dedup() -> None:
    pred = _op("concept:eq", _var("a"), _op("+", _var("b"), _var("a")))
    assert pt.free_vars(pred) == ["a", "b"]
