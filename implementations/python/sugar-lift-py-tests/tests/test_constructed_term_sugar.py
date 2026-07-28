"""Closed constructed-Sugar canonical term admission."""

from dataclasses import dataclass, replace
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.call_contract_resolution import ResolvedCallContractRefV1
from sugar_lift_py_tests.ir import PrimitiveSort, str_const
from sugar_lift_py_tests.generator_construction import YieldStepV1
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.collection_sugar import (
    DictSugar,
    ListSugar,
    SetSugar,
    TupleSugar,
)
from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionGeneratorSugar,
    ComprehensionSugar,
    ComprehensionTargetSugar,
)
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.fstring_sugar import FormattedValueSugar, JoinedStrSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.subscript_sugar import SubscriptSugar
from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


class _MissingTerm(ConstructedTermSugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError


class _ArbitrarySugar(Sugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError


@dataclass(frozen=True)
class _Operand(ConstructedTermSugar):
    testimony: str

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError

    def to_term(self, *, owner: str):
        del owner
        return str_const(self.testimony)


@dataclass(frozen=True)
class _Coordinate:
    cid: str


def _call_sites():
    source = "callee(a, b)\ncallee(a, b)\n"
    tree = SourceFile((source, "calls.py", blake3_512_of(source.encode())))
    return tuple(node.fragment for node in tree.nodes() if node.kind == "Call")


def _comprehension_generator(iterable, *, filters=()):
    return ComprehensionGeneratorSugar(
        target=ComprehensionTargetSugar(source_name="item"),
        binding_coordinate_cid="blake3-512:" + "g" * 128,
        iterable=iterable,
        filters=filters,
    )


def _contract(letter: str) -> ResolvedCallContractRefV1:
    cid = "blake3-512:" + letter * 128
    return ResolvedCallContractRefV1(
        resolution_cid=cid,
        demand_cid="blake3-512:" + "d" * 128,
        use_site=None,
        import_binding_cid="blake3-512:" + "i" * 128,
        catalog_cid="blake3-512:" + "c" * 128,
        member_cid="blake3-512:" + "m" * 128,
        contract_cid=cid,
        bridge_source_symbol="ignored-spelling",
        formals=("value",),
        sorts=(PrimitiveSort("Value"),),
        return_term=None,
        source_warrant_cids=(),
        contract_decl=MappingProxyType({"kind": "contract"}),
    )


def _call(*, site=None, args=("a", "b"), keywords=(), definition="d", contract=None):
    if site is None:
        site = _call_sites()[0]
    coordinate = _Coordinate("blake3-512:" + definition * 128)
    return CallSiteSugar(
        target_name="ignored-spelling",
        args=tuple(_Operand(value) for value in args),
        keywords=tuple((name, _Operand(value)) for name, value in keywords),
        exception_type_coordinate=coordinate,
        contract_ref=contract,
        site=site,
    )


def test_missing_constructed_term_obligation_refuses_at_instantiation():
    with pytest.raises(TypeError, match="abstract method 'to_term'"):
        _MissingTerm()


def test_generator_payload_admission_refuses_arbitrary_sugar():
    with pytest.raises(TypeError, match="YieldStepV1.value requires ConstructedTermSugar"):
        YieldStepV1(_ArbitrarySugar())


@pytest.mark.parametrize(
    "build",
    (
        lambda child, site: EqualityOpSugar(child, _Operand("right"), site),
        lambda child, site: BoolOpSugar("And", (child, _Operand("right")), site),
        lambda child, site: TupleSugar((child,), site),
        lambda child, site: ListSugar((child,), site),
        lambda child, site: SetSugar((child,), site),
        lambda child, site: DictSugar((child,), (_Operand("value"),), site),
        lambda child, site: DictSugar((_Operand("key"),), (child,), site),
        lambda child, site: IfExpSugar(child, _Operand("body"), _Operand("else"), site),
        lambda child, site: CallSiteSugar("ignored", (child,), site),
        lambda child, site: CallSiteSugar("ignored", (), site, (("key", child),)),
        lambda child, site: AttributeSugar(child, "field", site),
        lambda child, site: ComputedCallSugar(child, (_Operand("arg"),), site),
        lambda child, site: ComputedCallSugar(_Operand("callee"), (child,), site),
        lambda child, site: ComputedCallSugar(
            _Operand("callee"), (), site, (("key", child),)
        ),
        lambda child, site: ComparisonOpSugar("Is", child, _Operand("right"), site),
        lambda child, site: MethodCallSugar(child, "method", (), site),
        lambda child, site: MethodCallSugar(
            _Operand("receiver"), "method", (child,), site
        ),
        lambda child, site: MethodCallSugar(
            _Operand("receiver"), "method", (), site, (("key", child),)
        ),
        lambda child, site: SubscriptSugar(child, _Operand("index"), site),
        lambda child, site: UnaryOpSugar("Not", child, site),
        lambda child, site: SliceSugar(child, None, None, site),
        lambda child, site: BinOpSugar("Add", child, _Operand("right"), site),
        lambda child, site: FormattedValueSugar(child, None, None, site),
        lambda child, site: JoinedStrSugar((child,), site),
        lambda child, site: ComprehensionSugar(
            "py.generatorexp",
            (_comprehension_generator(child),),
            _Operand("element"),
            site=site,
        ),
        lambda child, site: ComprehensionSugar(
            "py.generatorexp",
            (_comprehension_generator(_Operand("iterable"), filters=(child,)),),
            _Operand("element"),
            site=site,
        ),
        lambda child, site: ComprehensionSugar(
            "py.generatorexp",
            (_comprehension_generator(_Operand("iterable")),),
            child,
            site=site,
        ),
        lambda child, site: ComprehensionSugar(
            "py.dictcomp",
            (_comprehension_generator(_Operand("iterable")),),
            _Operand("value"),
            key=child,
            site=site,
        ),
    ),
    ids=(
        "equality",
        "bool-op",
        "tuple",
        "list",
        "set",
        "dict-key",
        "dict-value",
        "if-expression",
        "call-arg",
        "call-keyword",
        "attribute",
        "computed-callee",
        "computed-arg",
        "computed-keyword",
        "comparison",
        "method-receiver",
        "method-arg",
        "method-keyword",
        "subscript",
        "unary-op",
        "slice",
        "binary-op",
        "formatted-value",
        "joined-string",
        "comprehension-iterable",
        "comprehension-filter",
        "comprehension-element",
        "comprehension-key",
    ),
)
def test_constructed_term_nested_children_are_closed_at_construction(build):
    site = _call_sites()[0]
    assert isinstance(build(_Operand("good"), site), ConstructedTermSugar)
    with pytest.raises(TypeError, match="requires ConstructedTermSugar"):
        build(_ArbitrarySugar(), site)


def test_equivalent_call_reconstruction_has_the_same_term():
    site = _call_sites()[0]
    assert _call(site=site).to_term(owner="first") == _call(site=site).to_term(
        owner="second"
    )


def test_changed_resolved_contract_authority_changes_call_term():
    assert _call(contract=_contract("a")).to_term(
        owner="first-contract"
    ) != _call(contract=_contract("b")).to_term(owner="second-contract")


@pytest.mark.parametrize(
    "variant",
    (
        _call(site=_call_sites()[1]),
        _call(args=("b", "a")),
        _call(args=("a", "changed")),
        _call(keywords=(("left", "a"), ("right", "b"))),
        _call(keywords=(("right", "b"), ("left", "a"))),
        _call(definition="e"),
        _call(contract=_contract("a")),
        _call(contract=_contract("b")),
    ),
    ids=(
        "occurrence",
        "argument-order",
        "argument-testimony",
        "keyword-arguments",
        "keyword-order",
        "definition-coordinate",
        "first-contract-authority",
        "changed-contract-authority",
    ),
)
def test_changed_call_preimage_changes_term(variant):
    assert _call().to_term(owner="baseline") != variant.to_term(owner="variant")


@pytest.mark.parametrize(
    "build",
    (
        lambda site: ListSugar((_Operand("a"), _Operand("b")), site),
        lambda site: SetSugar((_Operand("a"), _Operand("b")), site),
        lambda site: DictSugar(
            (_Operand("a"), _Operand("b")),
            (_Operand("1"), _Operand("2")),
            site,
        ),
    ),
    ids=("list", "set", "dict"),
)
def test_collection_reconstruction_and_occurrence_discriminate(build):
    first, second = _call_sites()
    assert build(first).to_term(owner="first") == build(first).to_term(
        owner="reconstructed"
    )
    assert build(first).to_term(owner="first") != build(second).to_term(
        owner="second"
    )


@pytest.mark.parametrize(
    "build",
    (
        lambda site, values: ListSugar(tuple(_Operand(v) for v in values), site),
        lambda site, values: SetSugar(tuple(_Operand(v) for v in values), site),
    ),
    ids=("list", "set"),
)
def test_ordered_collection_child_testimony_discriminates(build):
    site = _call_sites()[0]
    assert build(site, ("a", "b")).to_term(owner="forward") != build(
        site, ("b", "a")
    ).to_term(owner="reverse")


def test_dict_term_preserves_exact_ordered_key_value_pairing():
    site = _call_sites()[0]
    baseline = DictSugar(
        (_Operand("k1"), _Operand("k2")),
        (_Operand("v1"), _Operand("v2")),
        site,
    )
    crossed = DictSugar(
        (_Operand("k1"), _Operand("k2")),
        (_Operand("v2"), _Operand("v1")),
        site,
    )
    reordered_pairs = DictSugar(
        (_Operand("k2"), _Operand("k1")),
        (_Operand("v2"), _Operand("v1")),
        site,
    )

    term = baseline.to_term(owner="baseline")
    assert term != crossed.to_term(owner="crossed")
    assert term != reordered_pairs.to_term(owner="reordered")
    assert term.name == "python:dict-construction"
    pairs = term.args[1]
    assert pairs.name == "python:dict-entries"
    assert [pair.name for pair in pairs.args] == ["python:dict-entry"] * 2


def test_dict_key_value_arity_mismatch_refuses_at_construction():
    with pytest.raises(ValueError, match="equal key/value arity"):
        DictSugar((_Operand("key"),), (), _call_sites()[0])
