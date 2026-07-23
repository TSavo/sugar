from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import EffectMatcher, Expects
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.with_manager_authority import (
    AuthenticatedLegacyMembrane,
    AuthenticatedLegacyMembraneRefV1,
    ConflictingAuthority,
    UnresolvedContextManager,
    WithManagerAuthorityProtocolError,
    WithManagerAuthoritiesV1,
    decode_with_manager_authorities,
)
from sugar_lift_py_tests.lift_rpc import _legacy_membrane_token_rows


def _cid(fill: str) -> str:
    return "blake3-512:" + fill * 128


def _site() -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1(_cid("s"), 4, 9, 4, 25)


def _unresolved():
    return ContextManagerResolutionGapV1(
        _cid("d"), _site(), "context-manager:dependency.manager",
        "unresolved-symbol", (),
    )


def _refs():
    return ResolvedContractRefsV1(
        _cid("c"), _cid("t"), MappingProxyType({_site(): _unresolved()})
    )


def _token():
    return AuthenticatedLegacyMembraneRefV1.mint_from_authenticated_identity(
        demand_cid=_cid("d"), use_site=_site(),
        manifest_cid=_cid("m"),
        enrollment_cid=_cid("e"),
        contract=Expects(EffectMatcher("raise", "ValueError"), "exception_info"),
    )


def test_unresolved_without_token_stays_the_exact_typed_gap():
    table = WithManagerAuthoritiesV1.assemble(_refs(), ())
    authority = table.require(_site())
    assert isinstance(authority, UnresolvedContextManager)
    assert authority.gap == _refs().require(_site())


def test_authenticated_token_wins_only_over_underlying_unresolved_row_and_round_trips():
    token = _token()
    table = WithManagerAuthoritiesV1.assemble(_refs(), (token,))
    authority = table.require(_site())
    assert isinstance(authority, AuthenticatedLegacyMembrane)
    assert authority.reference == token
    decoded = decode_with_manager_authorities(table.to_wire())
    assert decoded == table
    assert decoded.require(_site()).reference.demand_cid == _cid("d")


def test_duplicate_tokens_are_conflicting_authority_not_first_match():
    table = WithManagerAuthoritiesV1.assemble(_refs(), (_token(), _token()))
    authority = table.require(_site())
    assert isinstance(authority, ConflictingAuthority)
    assert authority.gap.kind == "duplicate-legacy-membrane-token"


@pytest.mark.parametrize("field", [
    "authenticationCid", "demandCid", "manifestCid", "enrollmentCid",
])
def test_mutated_authenticated_token_is_loud(field):
    table = WithManagerAuthoritiesV1.assemble(_refs(), (_token(),))
    wire = table.to_wire()
    wire["byUseSite"][0]["authority"]["reference"][field] = _cid("z")
    with pytest.raises(WithManagerAuthorityProtocolError):
        decode_with_manager_authorities(wire)


def test_preconstruction_prebinder_authenticates_alias_but_not_same_spelled_local(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from pytest import raises as expect_error\n"
        "def admitted():\n"
        "    with expect_error(ValueError) as caught:\n"
        "        return caught\n"
        "def raises(value):\n"
        "    return value\n"
        "def local():\n"
        "    with raises(ValueError):\n"
        "        pass\n"
    )
    rows = _legacy_membrane_token_rows(tmp_path)
    assert len(rows) == 1
    token = rows[0]
    assert token["kind"] == "authenticated-legacy-membrane-ref"
    assert token["demandCid"].startswith("blake3-512:")
    assert token["contract"]["kind"] == "expects"
    assert token["contract"]["matcher"]["name"] == "ValueError"
