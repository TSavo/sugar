"""Undecided-attribution: write-more-Floor must not swallow source-undecided lookups.

Law (FloorValue.attribute / subscript / contains defaults):

- denotes a value AND runtime type is NOT source-decided
  → existing undecided_* named refusal (SugarNotWritten)
- runtime type IS decided but the arm is missing
  → construction panic "write more Floor" (OUR debt)

Misrouting the first case into the second inflates remaining work as if the
kit owed code when the source simply never decided the type. That number then
lies about what is left to build.

This instrument pins the two-door discrimination on the base FloorValue so
every future floor that correctly testifies ``runtime_type_is_decided`` is
False inherits the honest path — no per-type override required for lookup.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
from sugar_lift_py_tests.floor.mutable_global_value import MutableGlobalValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten

SITE = "undecided-lookup-attribution-site"


class _UndecidedPlant(FloorValue):
    """Minimal value whose runtime type is source-undecided.

    No attribute/subscript/contains override — must enter FloorValue defaults.
    """

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return False

    def to_term(self, *, owner: str):
        del owner
        return make_var("undecided_plant")


class _DecidedMissingArm(FloorValue):
    """Decided-type value with no lookup arms — honest write-more-Floor debt."""

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return True

    def to_term(self, *, owner: str):
        del owner
        return make_var("decided_missing")


class _NonValueUndecided(FloorValue):
    """Does not denote a value; undecided rtd must not open the value door."""

    def denotes_value(self) -> bool:
        return False

    def runtime_type_is_decided(self) -> bool:
        return False

    def to_term(self, *, owner: str):
        del owner
        return make_var("not_a_value")


def _assert_named_refusal_not_write_more(exc: BaseException) -> None:
    assert isinstance(exc, SugarNotWritten)
    assert not isinstance(exc, ConstructionPanic)
    text = str(exc)
    assert "write more Floor" not in text
    assert "undecided" in (getattr(exc, "observed", "") or text).lower()


@pytest.mark.parametrize(
    "method,args",
    (
        ("attribute", ("x", SITE)),
        ("subscript", (TermValue(0), SITE)),
        ("contains", (TermValue(1), SITE)),
    ),
)
def test_undecided_plant_uses_named_refusal_not_write_more_floor(method, args) -> None:
    """The base FloorValue door is the instrument — no per-type override."""
    plant = _UndecidedPlant()
    assert plant.denotes_value() is True
    assert plant.runtime_type_is_decided() is False
    with pytest.raises(SugarNotWritten) as raised:
        getattr(plant, method)(*args)
    _assert_named_refusal_not_write_more(raised.value)
    assert raised.value.owner == f"_UndecidedPlant.{method}"


@pytest.mark.parametrize(
    "method,args",
    (
        ("attribute", ("x", SITE)),
        ("subscript", (TermValue(0), SITE)),
        ("contains", (TermValue(1), SITE)),
    ),
)
def test_decided_missing_arm_stays_write_more_floor(method, args) -> None:
    """Truthful twin: decided type without an arm is still OUR construction debt."""
    plant = _DecidedMissingArm()
    with pytest.raises(ConstructionPanic) as raised:
        getattr(plant, method)(*args)
    assert "write more Floor" in raised.value.info.fix
    assert raised.value.info.observed == "_DecidedMissingArm"


@pytest.mark.parametrize(
    "method,args",
    (
        ("attribute", ("x", SITE)),
        ("subscript", (TermValue(0), SITE)),
        ("contains", (TermValue(1), SITE)),
    ),
)
def test_non_value_does_not_steal_undecided_door(method, args) -> None:
    """denotes_value False keeps construction panic even when rtd is False."""
    plant = _NonValueUndecided()
    with pytest.raises(ConstructionPanic) as raised:
        getattr(plant, method)(*args)
    assert "write more Floor" in raised.value.info.fix


def test_symbolic_and_callsite_remain_named_refusal() -> None:
    """Regression: existing undecided floors stay on the named-refusal path."""
    with pytest.raises(SugarNotWritten) as sym:
        SymbolicValue(make_var("s")).attribute("x", SITE)
    _assert_named_refusal_not_write_more(sym.value)

    call = CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
    with pytest.raises(SugarNotWritten) as cs:
        call.subscript(TermValue(0), SITE)
    _assert_named_refusal_not_write_more(cs.value)


def test_import_member_lookup_is_undecided_not_write_more_floor() -> None:
    """Live offender class: ImportMemberValue has no attr/sub/con overrides.

    It testifies denotes_value + not runtime_type_is_decided. Before the base
    two-door law, default FloorValue miscounted this as write-more-Floor debt.
    """
    member = _mint_import_member()
    assert member.denotes_value() is True
    assert member.runtime_type_is_decided() is False
    # No local override — the base door must carry the law.
    assert type(member).attribute is FloorValue.attribute
    assert type(member).subscript is FloorValue.subscript
    assert type(member).contains is FloorValue.contains

    site = "import-member-undecided-lookup"
    with pytest.raises(SugarNotWritten) as attr:
        member.attribute("bit_count", site)
    _assert_named_refusal_not_write_more(attr.value)
    assert attr.value.owner == "ImportMemberValue.attribute"

    with pytest.raises(SugarNotWritten) as sub:
        member.subscript(TermValue(0), site)
    _assert_named_refusal_not_write_more(sub.value)

    with pytest.raises(SugarNotWritten) as con:
        member.contains(TermValue(1), site)
    _assert_named_refusal_not_write_more(con.value)


def test_mutable_global_non_dict_pin_is_source_undecided() -> None:
    """Non-dict mutable pin: type not decided → undecided_*, not write-more-Floor."""
    from sugar_source_tree.fragment import SourceMemento

    pin_cid = "cid:source:mutable-undecided"
    memento = SourceMemento(
        file="pin.py",
        start=0,
        end=1,
        source_cid=pin_cid,
        cid="cid:binding:mutable-undecided",
    )
    value = MutableGlobalValue("G", "object", pin_cid, memento)
    assert value.denotes_value() is True
    assert value.runtime_type_is_decided() is False

    with pytest.raises(SugarNotWritten) as attr:
        value.attribute("name", SITE)
    _assert_named_refusal_not_write_more(attr.value)

    with pytest.raises(SugarNotWritten) as sub:
        value.subscript(TermValue(0), SITE)
    _assert_named_refusal_not_write_more(sub.value)

    with pytest.raises(SugarNotWritten) as con:
        value.contains(TermValue(1), SITE)
    _assert_named_refusal_not_write_more(con.value)


def test_mutable_global_dict_pin_keeps_decided_container_type() -> None:
    """Dict pin remains type-decided so container arms stay construction, not undecided."""
    from sugar_source_tree.fragment import SourceMemento

    pin_cid = "cid:source:mutable-dict"
    memento = SourceMemento(
        file="pin.py",
        start=0,
        end=1,
        source_cid=pin_cid,
        cid="cid:binding:mutable-dict",
    )
    value = MutableGlobalValue("OPTIONS", "dict", pin_cid, memento)
    assert value.runtime_type_is_decided() is True
    # Attribute still has no dict-pin arm → honest write-more-Floor debt.
    with pytest.raises(ConstructionPanic) as raised:
        value.attribute("keys", SITE)
    assert "write more Floor" in raised.value.info.fix


def test_source_decided_none_contains_still_type_error() -> None:
    """Decided non-container must not be reclassified as undecided."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import Compare
    from sugar_source_tree.tree import SourceFile

    # Ground TypeError requires a real source fragment (not a prose string site).
    source = "def f():\n    return 1 in None\n"
    tree = SourceFile(
        (source, "in-none.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    site = next(
        node.fragment for node in tree.nodes() if isinstance(node, Compare)
    )
    outcome = NoneValue().contains(TermValue(1), site)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def _mint_import_member() -> ImportMemberValue:
    """Seat a real ImportMemberValue through the production import receipt path."""
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.nodes import Attribute, ClassDef
    from sugar_source_tree.tree import SourceFile

    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    regex_flag = next(
        node
        for node in source_file.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=regex_flag,
        session=SourceResolutionSession(enabled=False),
        context=context,
        dependency_graphs={"re": graph},
    )
    member = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute) and node.attr == "SRE_FLAG_ASCII"
    )
    outcome = member.sugar().desugar()
    assert isinstance(outcome, Complete)
    assert type(outcome.value) is ImportMemberValue
    return outcome.value
