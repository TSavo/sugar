"""Closed constructed-Sugar canonical term admission."""

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.generator_construction import YieldStepV1
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
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


def _call(*, site=None, args=("a", "b"), keywords=(), definition="d"):
    if site is None:
        site = _call_sites()[0]
    coordinate = _Coordinate("blake3-512:" + definition * 128)
    return CallSiteSugar(
        target_name="ignored-spelling",
        args=tuple(_Operand(value) for value in args),
        keywords=tuple((name, _Operand(value)) for name, value in keywords),
        exception_type_coordinate=coordinate,
        site=site,
    )


def test_missing_constructed_term_obligation_refuses_at_instantiation():
    with pytest.raises(TypeError, match="abstract method 'to_term'"):
        _MissingTerm()


def test_generator_payload_admission_refuses_arbitrary_sugar():
    with pytest.raises(TypeError, match="YieldStepV1.value requires ConstructedTermSugar"):
        YieldStepV1(_ArbitrarySugar())


def test_equivalent_call_reconstruction_has_the_same_term():
    site = _call_sites()[0]
    assert _call(site=site).to_term(owner="first") == _call(site=site).to_term(
        owner="second"
    )


@pytest.mark.parametrize(
    "variant",
    (
        _call(site=_call_sites()[1]),
        _call(args=("b", "a")),
        _call(args=("a", "changed")),
        _call(keywords=(("left", "a"), ("right", "b"))),
        _call(keywords=(("right", "b"), ("left", "a"))),
        _call(definition="e"),
    ),
    ids=(
        "occurrence",
        "argument-order",
        "argument-testimony",
        "keyword-arguments",
        "keyword-order",
        "definition-coordinate",
    ),
)
def test_changed_call_preimage_changes_term(variant):
    assert _call().to_term(owner="baseline") != variant.to_term(owner="variant")
