"""SetComp / DictComp / GeneratorExp: py.setcomp / py.dictcomp / py.genexp.

Mirror ListCompSugar: single-generator simple-Name target; carry all parts on
the comprehension coordinate; multi-generator and tuple-target stay loud.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.sugar.dict_comp_sugar import DictCompSugar
from sugar_lift_py_tests.sugar.generator_exp_sugar import GeneratorExpSugar
from sugar_lift_py_tests.sugar.list_comp_sugar import ListCompSugar
from sugar_lift_py_tests.sugar.set_comp_sugar import SetCompSugar


def _site(expr: str):
    node = ast.parse(expr, mode="eval").body
    return SourceFragment.from_node(node, "t.py")


def _xs():
    return {"xs": SymbolicValue(make_var("xs"))}


def _ys():
    return {"ys": SymbolicValue(make_var("ys"))}


# ---------------------------------------------------------------------------
# SetComp
# ---------------------------------------------------------------------------


def test_set_comp_reduces_to_setcomp_coordinate() -> None:
    value = reduce_value("{x for x in xs}", binds=_xs())
    assert isinstance(value, SymbolicValue)
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert value.term == ctor("py.setcomp", [elem, make_var("xs")])


def test_set_comp_elt_and_iter_discriminate() -> None:
    plain = reduce_value("{x for x in xs}", binds=_xs())
    doubled = reduce_value("{x * 2 for x in xs}", binds=_xs())
    from_ys = reduce_value("{x for x in ys}", binds=_ys())
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert doubled.term == ctor(
        "py.setcomp", [ctor("*", [elem, num(2)]), make_var("xs")]
    )
    assert plain.term != doubled.term
    assert plain.term != from_ys.term


def test_set_comp_owns_only_setcomp_single_name() -> None:
    assert SetCompSugar.owns(_site("{x for x in xs}")) is True
    assert SetCompSugar.owns(_site("{x for a in A for b in B}")) is False
    assert SetCompSugar.owns(_site("{x for (x, y) in pairs}")) is False
    assert SetCompSugar.owns(_site("[x for x in xs]")) is False
    assert SetCompSugar.owns(_site("{x: x for x in xs}")) is False
    assert SetCompSugar.owns(_site("(x for x in xs)")) is False


def test_set_comp_multi_generator_is_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("{x for a in A for b in B}")
    assert raised.value.info.observed == "SetComp"


# ---------------------------------------------------------------------------
# DictComp -- BOTH key and value ride
# ---------------------------------------------------------------------------


def test_dict_comp_carries_key_value_and_iter() -> None:
    """{x: x * 2 for x in xs} carries key, value, and iter -- never drops either."""
    value = reduce_value("{x: x * 2 for x in xs}", binds=_xs())
    assert isinstance(value, SymbolicValue)
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert value.term == ctor(
        "py.dictcomp",
        [elem, ctor("*", [elem, num(2)]), make_var("xs")],
    )


def test_dict_comp_key_and_value_discriminate() -> None:
    same = reduce_value("{x: x for x in xs}", binds=_xs())
    doubled = reduce_value("{x: x * 2 for x in xs}", binds=_xs())
    key_doubled = reduce_value("{x * 2: x for x in xs}", binds=_xs())
    assert same.term != doubled.term
    assert same.term != key_doubled.term
    assert doubled.term != key_doubled.term


def test_dict_comp_owns_only_dictcomp_single_name() -> None:
    assert DictCompSugar.owns(_site("{x: x for x in xs}")) is True
    assert DictCompSugar.owns(_site("{x: x for a in A for b in B}")) is False
    assert DictCompSugar.owns(_site("{k: v for (k, v) in pairs}")) is False
    assert DictCompSugar.owns(_site("[x for x in xs]")) is False
    assert DictCompSugar.owns(_site("{x for x in xs}")) is False
    assert DictCompSugar.owns(_site("(x for x in xs)")) is False


def test_dict_comp_tuple_target_is_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("{k: v for (k, v) in pairs}")
    assert raised.value.info.observed == "DictComp"


# ---------------------------------------------------------------------------
# GeneratorExp
# ---------------------------------------------------------------------------


def test_genexp_reduces_to_genexp_coordinate() -> None:
    value = reduce_value("(x for x in xs)", binds=_xs())
    assert isinstance(value, SymbolicValue)
    elem = ctor("py.iter_elem", [make_var("xs")])
    assert value.term == ctor("py.genexp", [elem, make_var("xs")])


def test_genexp_elt_and_iter_discriminate() -> None:
    plain = reduce_value("(x for x in xs)", binds=_xs())
    doubled = reduce_value("(x * 2 for x in xs)", binds=_xs())
    from_ys = reduce_value("(x for x in ys)", binds=_ys())
    assert plain.term != doubled.term
    assert plain.term != from_ys.term


def test_genexp_owns_only_genexp_single_name() -> None:
    assert GeneratorExpSugar.owns(_site("(x for x in xs)")) is True
    assert GeneratorExpSugar.owns(_site("(x for a in A for b in B)")) is False
    assert GeneratorExpSugar.owns(_site("(x for (x, y) in pairs)")) is False
    assert GeneratorExpSugar.owns(_site("[x for x in xs]")) is False
    assert GeneratorExpSugar.owns(_site("{x for x in xs}")) is False
    assert GeneratorExpSugar.owns(_site("{x: x for x in xs}")) is False


def test_genexp_multi_generator_is_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        reduce_value("(x for a in A for b in B)")
    assert raised.value.info.observed == "GeneratorExp"


# ---------------------------------------------------------------------------
# Cross-kind structural isolation
# ---------------------------------------------------------------------------


def test_kinds_do_not_cross_own() -> None:
    """Each sugar owns only its observed kind; ListComp is not a sibling owner."""
    list_site = _site("[x for x in xs]")
    set_site = _site("{x for x in xs}")
    dict_site = _site("{x: x for x in xs}")
    gen_site = _site("(x for x in xs)")

    assert ListCompSugar.owns(list_site) and not ListCompSugar.owns(set_site)
    assert SetCompSugar.owns(set_site) and not SetCompSugar.owns(list_site)
    assert DictCompSugar.owns(dict_site) and not DictCompSugar.owns(list_site)
    assert GeneratorExpSugar.owns(gen_site) and not GeneratorExpSugar.owns(list_site)

    catalog = default_catalog()
    set_names = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, set_site)
    ]
    dict_names = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, dict_site)
    ]
    gen_names = [
        c.name for c in catalog.candidates_for(SugarRole.TERM, gen_site)
    ]
    assert "SetCompSugar" in set_names
    assert "DictCompSugar" in dict_names
    assert "GeneratorExpSugar" in gen_names
    assert "ListCompSugar" not in set_names
