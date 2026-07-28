"""Closed constructed-Sugar canonical term admission."""

from dataclasses import dataclass, replace
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.call_contract_resolution import ResolvedCallContractRefV1
from sugar_lift_py_tests.ir import PrimitiveSort, str_const
from sugar_lift_py_tests.generator_construction import YieldStepV1
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
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
        lambda child, site: IfExpSugar(child, _Operand("body"), _Operand("else"), site),
        lambda child, site: CallSiteSugar("ignored", (child,), site),
        lambda child, site: CallSiteSugar("ignored", (), site, (("key", child),)),
    ),
    ids=("equality", "bool-op", "tuple", "if-expression", "call-arg", "call-keyword"),
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
