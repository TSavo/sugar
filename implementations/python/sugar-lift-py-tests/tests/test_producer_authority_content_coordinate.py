"""A producer authority is a capability that can also be SAID.

The defect these teeth stand over: ``_OPAQUE_CITED_MANAGER_AUTHORITY`` was a
bare ``object()`` riding on ``OpaqueCitedContextManagerRefV1._authority``. That
ref rides on ``WithOpaqueCitedManagerSugar.contract_ref``, and that node reaches
content-addressing. ``ConstructedValueV2`` walks every dataclass field, met
``builtins.object``, and refused with::

    unclassified constructed value category builtins.object
    [refused at .contract_ref._authority of ...WithOpaqueCitedManagerSugar]

The refusal named a missing CATEGORY. The truth was a slot that HAD no content
-- a process address, not a value. Two faults in one wearing: "I cannot name
this category" and "this slot is unnameable by construction".

The repair splits them by NAMING the capability, not by widening a category.
Both halves are load-bearing and each has its own tooth below:

* the authority still gates on ``is`` -- a value-equal forgery holds nothing;
* a bare ``object()`` in a constructed value STILL refuses, and must.
"""

from dataclasses import dataclass, fields

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    _OPAQUE_CITED_MANAGER_AUTHORITY,
    ContractRefProtocolError,
    OpaqueCitedContextManagerRefV1,
    OpaqueSourceCallObligationV1,
    SourceFragmentCoordinateV1,
    mint_opaque_cited_context_manager_ref,
    opaque_source_call_roster_of,
)
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    constructed_value_cid_v2,
)
from sugar_source_tree.producer_authority import ProducerAuthorityV1

SOURCE_CID = "blake3-512:" + "aa" * 64
OWNER_CID = "blake3-512:" + "bb" * 64


@dataclass(frozen=True)
class Frag:
    filename: str = "t.py"
    line: int = 10
    col: int = 4
    source_cid: str = SOURCE_CID


@dataclass(frozen=True)
class ManagerSugar(Sugar):
    """A cited manager operand: an opaque call-site term, never a body."""

    name: str = "pytest.raises"

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        return Complete(
            SymbolicValue(ctor(f"call:{self.name}", [str_const("ValueError")]))
        )


def _coordinate(line: int = 10) -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1(SOURCE_CID, line, 4, line, 30)


def _ref(line: int = 10):
    roster = opaque_source_call_roster_of(
        OpaqueSourceCallObligationV1(
            _coordinate(line),
            "pytest.raises",
            OWNER_CID,
            "call-target-off-population",
        )
    )
    return mint_opaque_cited_context_manager_ref(roster=roster)


def _node(ref=None):
    return WithOpaqueCitedManagerSugar(
        manager=ManagerSugar(),
        body=(),
        contract_ref=ref if ref is not None else _ref(),
        site=Frag(),
    )


# ------------------------------------------------------- the repaired road


def test_cited_manager_with_reaches_a_content_coordinate():
    """THE ROW. This is the wall the 12 slice panics stood against.

    Mutation-proof: respell ``_OPAQUE_CITED_MANAGER_AUTHORITY`` as ``object()``
    and this raises ``ConstructedValueCategoryGap`` naming
    ``.contract_ref._authority`` -- the measured pre-repair refusal, verbatim.
    """
    cid = constructed_value_cid_v2(_node())
    assert cid.startswith("blake3-512:")


def test_the_authority_slot_is_the_slot_that_used_to_refuse():
    """Name the slot, so a future respelling cannot quietly move the fault."""
    assert "_authority" in {f.name for f in fields(_ref())}
    assert type(_ref()._authority) is ProducerAuthorityV1


def test_distinct_citations_keep_distinct_content_coordinates():
    """The authority is a constant; it must not flatten the values it rides.

    A shared constant in every preimage could only ever ADD a common term. If
    this ever went equal, the authority would be doing the addressing instead
    of the citation.
    """
    assert constructed_value_cid_v2(_node(_ref(10))) != constructed_value_cid_v2(
        _node(_ref(77))
    )


# ------------------------------------------------- the half that must NOT move


def test_a_bare_object_in_a_constructed_value_still_refuses():
    """DO NOT BROADEN. The repair names one category; it opens no catch-all.

    Mutation-proof: add a catch-all arm to ``_cv2_entries`` returning
    ``(tag, [])`` for an unclassified value and this goes green -- which is the
    outcome that would make every future unnameable slot silently addressable.
    """

    @dataclass(frozen=True)
    class CarriesABareObject:
        payload: object

    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2(CarriesABareObject(object()))
    assert "unclassified constructed value category builtins.object" in str(
        caught.value
    )
    assert ".payload" in str(caught.value)


def test_naming_the_authority_did_not_make_it_grantable():
    """The capability rides on IDENTITY. A value-equal forgery holds nothing.

    Mutation-proof: change ``__post_init__``'s ``is not`` to ``!=`` and this
    goes green -- a consumer could then mint a citation the producer never
    authorized, which is the whole point of the gate.
    """
    forgery = ProducerAuthorityV1(_OPAQUE_CITED_MANAGER_AUTHORITY.name)
    assert forgery == _OPAQUE_CITED_MANAGER_AUTHORITY
    assert forgery is not _OPAQUE_CITED_MANAGER_AUTHORITY

    clone = object.__new__(OpaqueCitedContextManagerRefV1)
    real = _ref()
    for name, value in (
        ("use_site", real.use_site),
        ("target_name", real.target_name),
        ("roster", real.roster),
        ("citation_cid", real.citation_cid),
        ("uncited", real.uncited),
        ("_authority", forgery),
    ):
        object.__setattr__(clone, name, value)
    with pytest.raises(ContractRefProtocolError) as raised:
        clone.__post_init__()
    assert "lacks producer authority" in str(raised.value)


def test_an_unnamed_authority_is_refused():
    """An unnamed capability is the bare ``object()`` again under a new class."""
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            ProducerAuthorityV1(bad)


# -------------------------------------------------- process-independent content


def test_the_authority_content_coordinate_is_pinned():
    """A PIN is the only honest test that this is content, not an address.

    An ``id()``-derived coordinate would differ on the next run, so a literal
    that keeps matching across processes IS the evidence.

    Mutation-proof: fold ``id(self)`` into the authority's canonical name and
    this fails on the first run after the mutation.
    """
    assert (
        constructed_value_cid_v2(_OPAQUE_CITED_MANAGER_AUTHORITY)
        == _PINNED_OPAQUE_CITED_MANAGER_AUTHORITY_CID
    )


def test_every_producer_authority_is_uniquely_named():
    """NO SHARED IDENTITY HUB. Two authorities sharing a name are one authority.

    This is not hypothetical: the mechanical respelling that produced these
    authorities gave ``_IMPORT_MEMBER_AUTHORITY`` the name of
    ``_MEMBER_AUTHORITY`` by substring collision. Two distinct minting doors
    were briefly indistinguishable in content. This tooth is why that was
    caught rather than shipped.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    seen: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        if "/tests/" in str(path):
            continue
        for match in re.finditer(
            r'^(\w+) = ProducerAuthorityV1\(\s*"([^"]+)"\s*\)',
            path.read_text(),
            flags=re.M | re.S,
        ):
            seen.setdefault(match.group(2), []).append(
                f"{path.name}::{match.group(1)}"
            )
    assert seen, "found no producer authorities to check -- the scan is broken"
    collisions = {name: who for name, who in seen.items() if len(who) > 1}
    assert not collisions, f"producer authorities sharing one name: {collisions}"


_PINNED_OPAQUE_CITED_MANAGER_AUTHORITY_CID = (
    "blake3-512:5df2b966822f2cf637c2ade9335cc9ec307e6dcf9f8d023491e1f90fed9937"
    "4477ce2aea409ef641ce39ac1d15b3fcc42df707546c0ad8908754f4609217d608"
)
