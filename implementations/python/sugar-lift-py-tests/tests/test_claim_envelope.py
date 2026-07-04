# SPDX-License-Identifier: MIT OR Apache-2.0
#
# claim_envelope tests: layered-shape construction, byte-equivalence
# against the Rust reference, error-path coverage, and the contractSet
# CID conformance test.
#
# Cross-kit byte-equivalence pins are derived from the Rust kit:
#   cargo test -p sugar-claim-envelope --test cross_kit_pin -- --nocapture
#
# The Rust kit is the reference; the Python kit must produce
# byte-identical output for the same canonical input. If a pin fails,
# the mismatch is a real divergence -- surface it, don't paper over it.

from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.canonicalizer import (
    blake3_512_of,
    encode_jcs,
    vobj,
    vstr,
    vint,
    varr,
)
from sugar_lift_py_tests.claim_envelope import (
    AuthoringKitAuthor,
    AuthoringLift,
    AuthoringLlm,
    ClaimEnvelope,
    EmptyContractError,
    EmptyOutBindingError,
    LAYERED_SCHEMA_VERSION,
    compute_contract_set_cid,
    contract_cid,
    mint_bridge,
    mint_contract,
    mint_implication,
)
from sugar_lift_py_tests.ir import ContractDecl, atomic, forall, gt, num, make_var, Int
from sugar_lift_py_tests.signing import (
    FOUNDATION_V0_SEED,
    Signer,
    ed25519_pubkey_string,
)

# ---------------------------------------------------------------------------
# Canonical fixtures (must match implementations/rust/.../tests/cross_kit_pin.rs)
# ---------------------------------------------------------------------------


# `forall n: Int. n > 0` -- the cross-kit pin's `pre` formula.
def _pre_n_gt_0_value():
    return vobj(
        [
            ("kind", vstr("forall")),
            ("name", vstr("n")),
            (
                "sort",
                vobj(
                    [
                        ("kind", vstr("primitive")),
                        ("name", vstr("Int")),
                    ]
                ),
            ),
            (
                "body",
                vobj(
                    [
                        ("kind", vstr("atomic")),
                        ("name", vstr(">")),
                        (
                            "args",
                            varr(
                                [
                                    vobj(
                                        [
                                            ("kind", vstr("var")),
                                            ("name", vstr("n")),
                                        ]
                                    ),
                                    vobj(
                                        [
                                            ("kind", vstr("const")),
                                            ("value", vint(0)),
                                            (
                                                "sort",
                                                vobj(
                                                    [
                                                        ("kind", vstr("primitive")),
                                                        ("name", vstr("Int")),
                                                    ]
                                                ),
                                            ),
                                        ]
                                    ),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
        ]
    )


# `out = 0` -- the cross-kit pin's `post` formula.
def _post_out_eq_0_value():
    return vobj(
        [
            ("kind", vstr("atomic")),
            ("name", vstr("=")),
            (
                "args",
                varr(
                    [
                        vobj(
                            [
                                ("kind", vstr("var")),
                                ("name", vstr("out")),
                            ]
                        ),
                        vobj(
                            [
                                ("kind", vstr("const")),
                                ("value", vint(0)),
                                (
                                    "sort",
                                    vobj(
                                        [
                                            ("kind", vstr("primitive")),
                                            ("name", vstr("Int")),
                                        ]
                                    ),
                                ),
                            ]
                        ),
                    ]
                ),
            ),
        ]
    )


def _fixture_kwargs():
    """Canonical fixture mirroring `fixture_args()` in
    implementations/rust/sugar-claim-envelope/tests/cross_kit_pin.rs.

    The pinned bytes/CIDs in TestCrossKitByteEquivalence below come from
    running that rust test. Any change to these inputs invalidates the
    pin; regenerate by running the rust test and updating the constants.
    """
    return dict(
        contract_name="demo",
        out_binding="out",
        pre=_pre_n_gt_0_value(),
        post=_post_out_eq_0_value(),
        inv=None,
        produced_by="rust-test@1.0",
        produced_at="2026-04-30T00:00:00.000Z",
        authoring=AuthoringKitAuthor(author="rust-test@1.0"),
        signer_seed=FOUNDATION_V0_SEED,
        input_cids=[],
    )


# ---------------------------------------------------------------------------
# Cross-kit byte-equivalence (pinned from Rust reference output)
#
# Generated by:
#   cargo test -p sugar-claim-envelope --test cross_kit_pin -- --nocapture
# ---------------------------------------------------------------------------

RUST_FIXTURE_BYTES_HEX_FULL = (
    "7b22656e76656c6f7065223a7b226465636c617265644174223a22323032362d30342d33"
    "305430303a30303a30302e3030305a222c227369676e6174757265223a22656432353531"
    "393a445549436e45753343647a4f76534a49756c5878314e4a794765746b73634f443755"
    "4857696b3264743733766d47332f375a2b763364673644516d6d6a4c744852556e793369"
    "454a61657a6c34326a6c584f655543513d3d222c227369676e6572223a22656432353531"
    "393a49564c34305a7435485352464d6b4c6858793672624c66502b6e747158744d416c35"
    "594f427069423278493d227d2c22686561646572223a7b2262696e64696e674861736822"
    "3a22626c616b65332d3531323a3465343962396465626338393963663865333461653931"
    "343662373234343832313139306662376631376136356534356561346265636465333033"
    "656337323865643636316132613336303763626432353361633730313264646534363836"
    "333737633664313966343464393633393232613465376539333034363932366466222c22"
    "636964223a22626c616b65332d3531323a62636130626239313434623362333565333261"
    "633039646334333832633838656336363337353031326235613166616663383965363539"
    "646239363637353637336435363161366436386234643138333138646330326638646437"
    "663838653665666661336439646262666237653764623137313631306630383731356462"
    "31222c22696e70757443696473223a5b5d2c226b696e64223a22636f6e7472616374222c"
    "226e616d65223a2264656d6f222c226f757442696e64696e67223a226f7574222c22706f"
    "7374223a7b2261726773223a5b7b226b696e64223a22766172222c226e616d65223a226f"
    "7574227d2c7b226b696e64223a22636f6e7374222c22736f7274223a7b226b696e64223a"
    "227072696d6974697665222c226e616d65223a22496e74227d2c2276616c7565223a307d"
    "5d2c226b696e64223a2261746f6d6963222c226e616d65223a223d227d2c22707265223a"
    "7b22626f6479223a7b2261726773223a5b7b226b696e64223a22766172222c226e616d65"
    "223a226e227d2c7b226b696e64223a22636f6e7374222c22736f7274223a7b226b696e64"
    "223a227072696d6974697665222c226e616d65223a22496e74227d2c2276616c7565223a"
    "307d5d2c226b696e64223a2261746f6d6963222c226e616d65223a223e227d2c226b696e"
    "64223a22666f72616c6c222c226e616d65223a226e222c22736f7274223a7b226b696e64"
    "223a227072696d6974697665222c226e616d65223a22496e74227d7d2c2270726f706572"
    "747948617368223a22626c616b65332d3531323a33636665633638326665646562336666"
    "656132346339373339653231343262633935323661636238653136326330303431386335"
    "363466383236663261363735633864616162636235313865366337663131666562363366"
    "346631336530373634353366643236623833323063336535356466393332383437313535"
    "65346132222c22736368656d6156657273696f6e223a2232222c2276657264696374223a"
    "22686f6c6473227d2c226d65746164617461223a7b22617574686f72696e67223a7b2261"
    "7574686f72223a22727573742d7465737440312e30222c2270726f64756365724b696e64"
    "223a226b69742d617574686f72227d2c22706f737448617368223a22626c616b65332d35"
    "31323a363530613835353463316362383831373832393965303637383238376638383939"
    "366636626633643733646139376238336539383330363264643565653736396338376631"
    "303830346561333333623237373937343366383837663661656266353235653734643836"
    "6662636165326461633964323937633235336536376135222c2270726548617368223a22"
    "626c616b65332d3531323a61663736323664646162346164343233636535653361326335"
    "633334643065616135346635373132303134376462663765396437363633323032633430"
    "396539303132383836663730303762616463386439366232396236623836333638646465"
    "32353461343237666466326632363138346263393834633036616239393232222c227072"
    "6f64756365644174223a22323032362d30342d33305430303a30303a30302e3030305a22"
    "2c2270726f64756365644279223a22727573742d7465737440312e30227d7d"
)


RUST_FIXTURE_CID = (
    "blake3-512:b5cd82094dd4d7dab5c73ab8b0f236a031a546335cd0ef1c0d7d70a23ffa3"
    "6506455b5d5a47e197a61da91fdc64b79901320a6480617ff0c0195526f3523639c"
)

RUST_FIXTURE_CONTRACT_CID = (
    "blake3-512:bca0bb9144b3b35e32ac09dc4382c88ec66375012b5a1fafc89e659db966"
    "75673d561a6d68b4d18318dc02f8dd7f88e6effa3d9dbbfb7e7db171610f08715db1"
)

# contractSetCid pin from the same rust generator: 2-element set
# {contract("demo"), contract("second")}.
RUST_CONTRACT_A_CID = (
    "blake3-512:bca0bb9144b3b35e32ac09dc4382c88ec66375012b5a1fafc89e659db966"
    "75673d561a6d68b4d18318dc02f8dd7f88e6effa3d9dbbfb7e7db171610f08715db1"
)
RUST_CONTRACT_B_CID = (
    "blake3-512:3a59a4b9fd854d194250159d08438539730533371e7b4b1ef71ff458accd"
    "394bc06e67a88d5ba56f7fe1a6f545843cfeb206ec53404b1820b9766d8d91b00e63"
)
RUST_CONTRACT_SET_CID = (
    "blake3-512:e42f67a1f994723791af102a0427c2563c63a526684a69a03264bc625aee"
    "b5081381a413ed5ce126800f5eb816d4c922e808cd325450825ef19933d075962506"
)


# ---------------------------------------------------------------------------
# Cross-kit byte-equivalence
# ---------------------------------------------------------------------------


class TestCrossKitByteEquivalence:
    """Python output must be byte-identical to Rust kit for the same input."""

    def test_fixture_bytes_match_rust(self):
        out = mint_contract(**_fixture_kwargs())
        rust_bytes = bytes.fromhex(RUST_FIXTURE_BYTES_HEX_FULL)
        if out.canonical_bytes != rust_bytes:
            for i, (p, r) in enumerate(zip(out.canonical_bytes, rust_bytes)):
                if p != r:
                    pytest.fail(
                        f"cross-kit byte divergence at byte {i}: "
                        f"python=0x{p:02x} ({chr(p) if 32 <= p < 127 else '?'}) "
                        f"rust=0x{r:02x} ({chr(r) if 32 <= r < 127 else '?'})\n"
                        f"python length: {len(out.canonical_bytes)}\n"
                        f"rust length:   {len(rust_bytes)}\n"
                        f"python[:200]:  {out.canonical_bytes[:200]!r}\n"
                        f"rust[:200]:    {rust_bytes[:200]!r}"
                    )
            pytest.fail(
                f"cross-kit length mismatch: python={len(out.canonical_bytes)}, "
                f"rust={len(rust_bytes)}"
            )

    def test_fixture_attestation_cid_matches_rust(self):
        out = mint_contract(**_fixture_kwargs())
        assert out.cid == RUST_FIXTURE_CID, (
            f"attestation CID mismatch:\n"
            f"  python: {out.cid}\n  rust:   {RUST_FIXTURE_CID}"
        )

    def test_fixture_contract_cid_matches_rust(self):
        out = mint_contract(**_fixture_kwargs())
        assert out.contract_cid == RUST_FIXTURE_CONTRACT_CID

    def test_contract_cid_function_matches_minted(self):
        """The standalone `contract_cid()` must equal the minted envelope's
        `contract_cid` field, since both compute the same thing."""
        kwargs = _fixture_kwargs()
        direct = contract_cid(
            contract_name=kwargs["contract_name"],
            out_binding=kwargs["out_binding"],
            pre=kwargs["pre"],
            post=kwargs["post"],
            inv=kwargs["inv"],
        )
        minted = mint_contract(**kwargs)
        assert direct == minted.contract_cid == RUST_FIXTURE_CONTRACT_CID

    def test_compute_contract_set_cid_matches_rust(self):
        """Per spec §1: BLAKE3-512(JCS(<sorted contractCids>))."""
        got = compute_contract_set_cid([RUST_CONTRACT_A_CID, RUST_CONTRACT_B_CID])
        assert got == RUST_CONTRACT_SET_CID, (
            f"contractSetCid mismatch:\n"
            f"  python: {got}\n  rust:   {RUST_CONTRACT_SET_CID}"
        )

    def test_compute_contract_set_cid_is_order_independent(self):
        a = compute_contract_set_cid([RUST_CONTRACT_A_CID, RUST_CONTRACT_B_CID])
        b = compute_contract_set_cid([RUST_CONTRACT_B_CID, RUST_CONTRACT_A_CID])
        assert a == b == RUST_CONTRACT_SET_CID


# ---------------------------------------------------------------------------
# Layered-shape structural conformance (envelope/header/metadata triple)
# ---------------------------------------------------------------------------


class TestLayeredShape:
    """Structural conformance with substrate-layers spec §1."""

    def _parse(self, env: ClaimEnvelope):
        return json.loads(env.canonical_bytes.decode("utf-8"))

    def test_top_level_has_three_keys(self):
        env = mint_contract(**_fixture_kwargs())
        parsed = self._parse(env)
        assert set(parsed.keys()) == {"envelope", "header", "metadata"}

    def test_envelope_has_signer_declared_at_signature(self):
        env = mint_contract(**_fixture_kwargs())
        parsed = self._parse(env)
        assert set(parsed["envelope"].keys()) == {"signer", "declaredAt", "signature"}
        assert parsed["envelope"]["signer"].startswith("ed25519:")
        assert parsed["envelope"]["signature"].startswith("ed25519:")

    def test_header_has_required_fields(self):
        env = mint_contract(**_fixture_kwargs())
        parsed = self._parse(env)
        h = parsed["header"]
        assert h["schemaVersion"] == LAYERED_SCHEMA_VERSION
        assert h["kind"] == "contract"
        assert h["cid"].startswith("blake3-512:")
        # Kind-specific REQUIRED for contract:
        for k in (
            "name",
            "outBinding",
            "verdict",
            "bindingHash",
            "propertyHash",
            "inputCids",
        ):
            assert k in h, f"header.{k} missing"

    def test_attestation_cid_equals_blake3_of_jcs_envelope(self):
        """Substrate-layers spec §2 R1: envelope CID = hash(JCS(envelope))
        AFTER signature is embedded."""
        env = mint_contract(**_fixture_kwargs())
        parsed = self._parse(env)
        # Reconstruct envelope as a Value tree and JCS it.
        e = parsed["envelope"]
        env_v = vobj(
            [
                ("signer", vstr(e["signer"])),
                ("declaredAt", vstr(e["declaredAt"])),
                ("signature", vstr(e["signature"])),
            ]
        )
        recomputed = blake3_512_of(encode_jcs(env_v).encode("utf-8"))
        assert (
            env.cid == recomputed
        ), "attestation CID must equal blake3_512(JCS(envelope))"

    def test_signature_covers_jcs_of_header_metadata(self):
        """Signature is over JCS({"header": header, "metadata": metadata})."""
        from nacl.signing import VerifyKey
        import base64

        env = mint_contract(**_fixture_kwargs())
        parsed = self._parse(env)

        # Reconstruct JCS({header, metadata}) -- the signed message.
        # We know it must verify, so re-emit via canonicalizer Values.
        # Easier: re-mint and compare against the same envelope's bytes.
        # For verification, decode the signature and check via libsodium.
        sig_str = parsed["envelope"]["signature"]
        signer_str = parsed["envelope"]["signer"]
        assert sig_str.startswith("ed25519:")
        assert signer_str.startswith("ed25519:")
        sig_bytes = base64.b64decode(sig_str[len("ed25519:") :])
        pk_bytes = base64.b64decode(signer_str[len("ed25519:") :])
        assert len(sig_bytes) == 64
        assert len(pk_bytes) == 32

        # The signed message is JCS({"header":..., "metadata":...}).
        # Recompute by JCS-encoding the parsed header/metadata back to
        # canonicalizer Values via a generic JSON-to-Value lift.
        signing_v = vobj(
            [
                ("header", _json_to_value(parsed["header"])),
                ("metadata", _json_to_value(parsed["metadata"])),
            ]
        )
        signing_bytes = encode_jcs(signing_v).encode("utf-8")

        VerifyKey(pk_bytes).verify(signing_bytes, sig_bytes)  # raises on failure


def _json_to_value(j):
    """Recursive JSON -> canonicalizer Value lift used in conformance tests."""
    if j is None:
        from sugar_lift_py_tests.canonicalizer import vnull

        return vnull()
    if isinstance(j, bool):
        from sugar_lift_py_tests.canonicalizer import vbool

        return vbool(j)
    if isinstance(j, int):
        return vint(j)
    if isinstance(j, str):
        return vstr(j)
    if isinstance(j, list):
        return varr([_json_to_value(x) for x in j])
    if isinstance(j, dict):
        return vobj([(k, _json_to_value(v)) for k, v in j.items()])
    raise TypeError(f"unsupported JSON type: {type(j)!r}")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_empty_contract_rejected(self):
        with pytest.raises(EmptyContractError):
            mint_contract(
                contract_name="x",
                out_binding="out",
                pre=None,
                post=None,
                inv=None,
                produced_by="t",
                produced_at="2026-04-30T00:00:00.000Z",
                authoring=AuthoringKitAuthor(author="t"),
                signer_seed=FOUNDATION_V0_SEED,
            )

    def test_empty_out_binding_rejected(self):
        with pytest.raises(EmptyOutBindingError):
            mint_contract(
                contract_name="x",
                out_binding="",
                pre=_pre_n_gt_0_value(),
                post=None,
                inv=None,
                produced_by="t",
                produced_at="2026-04-30T00:00:00.000Z",
                authoring=AuthoringKitAuthor(author="t"),
                signer_seed=FOUNDATION_V0_SEED,
            )


# ---------------------------------------------------------------------------
# from_contract_decl: ContractDecl wrapper
# ---------------------------------------------------------------------------


class TestFromContractDecl:
    """ClaimEnvelope.from_contract_decl(decl, signer) lowers the
    python `ContractDecl`'s Formula clauses to canonicalizer Values
    and delegates to mint_contract."""

    def test_from_contract_decl_round_trips(self):
        # forall n: Int. n > 0
        n = make_var("n")
        decl = ContractDecl(
            name="demo",
            pre=forall("n", Int(), gt(n, num(0))),
            post=None,
            inv=None,
            out_binding="out",
        )
        signer = Signer.foundation_v0(producer_id="py-kit@1.0")
        env = ClaimEnvelope.from_contract_decl(
            decl,
            signer,
            produced_at="2026-04-30T00:00:00.000Z",
        )
        assert env.cid.startswith("blake3-512:")
        assert env.contract_cid.startswith("blake3-512:")
        # Layered shape: parses as a triple.
        parsed = json.loads(env.canonical_bytes.decode("utf-8"))
        assert set(parsed.keys()) == {"envelope", "header", "metadata"}
        assert parsed["header"]["kind"] == "contract"
        assert parsed["header"]["name"] == "demo"

    def test_signer_producer_id_lands_in_metadata(self):
        n = make_var("n")
        decl = ContractDecl(
            name="demo",
            pre=forall("n", Int(), gt(n, num(0))),
            out_binding="out",
        )
        signer = Signer.foundation_v0(producer_id="py-kit@1.0")
        env = ClaimEnvelope.from_contract_decl(
            decl,
            signer,
            produced_at="2026-04-30T00:00:00.000Z",
        )
        parsed = json.loads(env.canonical_bytes.decode("utf-8"))
        assert parsed["metadata"]["producedBy"] == "py-kit@1.0"
        assert parsed["metadata"]["authoring"]["author"] == "py-kit@1.0"
        assert parsed["metadata"]["authoring"]["producerKind"] == "kit-author"

    def test_signer_sign_claim_delegates_to_from_contract_decl(self):
        """Signer.sign_claim is a convenience wrapper; bytes must be
        identical to ClaimEnvelope.from_contract_decl(decl, signer)."""
        n = make_var("n")
        decl = ContractDecl(
            name="demo",
            pre=forall("n", Int(), gt(n, num(0))),
            out_binding="out",
        )
        signer = Signer.foundation_v0(producer_id="py-kit@1.0")
        a = signer.sign_claim(decl, produced_at="2026-04-30T00:00:00.000Z")
        b = ClaimEnvelope.from_contract_decl(
            decl,
            signer,
            produced_at="2026-04-30T00:00:00.000Z",
        )
        assert a.canonical_bytes == b.canonical_bytes
        assert a.cid == b.cid
        assert a.contract_cid == b.contract_cid


# ---------------------------------------------------------------------------
# Authoring round-trip
# ---------------------------------------------------------------------------


class TestAuthoring:
    def _mint_with_authoring(self, authoring):
        return mint_contract(
            contract_name="x",
            out_binding="out",
            pre=_pre_n_gt_0_value(),
            produced_by="t",
            produced_at="2026-04-30T00:00:00.000Z",
            authoring=authoring,
            signer_seed=FOUNDATION_V0_SEED,
        )

    def test_kit_author_no_note_round_trips(self):
        env = self._mint_with_authoring(AuthoringKitAuthor(author="alice"))
        parsed = json.loads(env.canonical_bytes.decode("utf-8"))
        a = parsed["metadata"]["authoring"]
        assert a == {"producerKind": "kit-author", "author": "alice"}

    def test_kit_author_with_note_round_trips(self):
        env = self._mint_with_authoring(AuthoringKitAuthor(author="alice", note="hand"))
        a = json.loads(env.canonical_bytes.decode("utf-8"))["metadata"]["authoring"]
        assert a == {"producerKind": "kit-author", "author": "alice", "note": "hand"}

    def test_kit_author_empty_note_treated_as_absent(self):
        env = self._mint_with_authoring(AuthoringKitAuthor(author="alice", note=""))
        a = json.loads(env.canonical_bytes.decode("utf-8"))["metadata"]["authoring"]
        assert "note" not in a

    def test_lift_round_trips(self):
        env = self._mint_with_authoring(
            AuthoringLift(
                lifter="lift-kit@1.0",
                evidence="tests",
                source_cid="blake3-512:source",
            )
        )
        a = json.loads(env.canonical_bytes.decode("utf-8"))["metadata"]["authoring"]
        assert a["producerKind"] == "lift"
        assert a["lifter"] == "lift-kit@1.0"
        assert a["evidence"] == "tests"
        assert a["sourceCid"] == "blake3-512:source"

    def test_llm_confidence_truncates_toward_zero(self):
        """Match Rust's `(confidence * 1000.0) as i64` semantics: truncate,
        do NOT round. 0.9009 -> 900, not 901."""
        env = self._mint_with_authoring(
            AuthoringLlm(
                llm="claude",
                llm_version="opus-4.7",
                prompt_cid="blake3-512:p",
                confidence=0.9009,
                rationale=None,
            )
        )
        a = json.loads(env.canonical_bytes.decode("utf-8"))["metadata"]["authoring"]
        assert a["confidence"] == 900  # truncate, not round (would be 901)


# ---------------------------------------------------------------------------
# Determinism + sensitivity
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_bytes(self):
        a = mint_contract(**_fixture_kwargs())
        b = mint_contract(**_fixture_kwargs())
        assert a.canonical_bytes == b.canonical_bytes
        assert a.cid == b.cid

    def test_changing_pre_changes_cid(self):
        a = mint_contract(**_fixture_kwargs())
        kwargs = _fixture_kwargs()
        # Different pre formula
        kwargs["pre"] = vobj(
            [
                ("kind", vstr("atomic")),
                ("name", vstr("=")),
                ("args", varr([])),
            ]
        )
        b = mint_contract(**kwargs)
        assert a.cid != b.cid

    def test_changing_signer_changes_attestation_cid_not_contract_cid(self):
        """Two distinct signers attesting to the same contract produce
        different attestation CIDs but identical contract CIDs."""
        a = mint_contract(**_fixture_kwargs())
        kwargs = _fixture_kwargs()
        # Different seed
        kwargs["signer_seed"] = bytes([0x43] * 32)
        b = mint_contract(**kwargs)
        assert a.cid != b.cid
        assert a.contract_cid == b.contract_cid


# ---------------------------------------------------------------------------
# Bridge + implication smoke tests
# ---------------------------------------------------------------------------


class TestBridge:
    def test_mint_bridge_succeeds(self):
        env = mint_bridge(
            produced_by="t",
            produced_at="2026-04-30T00:00:00.000Z",
            source_symbol="parseInt",
            source_layer="ts",
            target_contract_cid="blake3-512:target",
            target_layer="rust",
            ir_arg_sorts=["String"],
            ir_return_sort="Int",
            notes="",
            signer_seed=FOUNDATION_V0_SEED,
        )
        assert env.cid.startswith("blake3-512:")
        assert env.contract_cid == ""  # empty for bridges
        parsed = json.loads(env.canonical_bytes.decode("utf-8"))
        assert parsed["header"]["kind"] == "bridge"
        assert parsed["header"]["sourceSymbol"] == "parseInt"


class TestImplication:
    def test_mint_implication_succeeds(self):
        env = mint_implication(
            produced_by="t",
            produced_at="2026-04-30T00:00:00.000Z",
            antecedent_hash="blake3-512:ah",
            consequent_hash="blake3-512:ch",
            antecedent_cid="blake3-512:acid",
            consequent_cid="blake3-512:bcid",
            antecedent_slot="pre",
            consequent_slot="post",
            prover="z3",
            prover_run_ms=42,
            signer_seed=FOUNDATION_V0_SEED,
        )
        assert env.cid.startswith("blake3-512:")
        assert env.contract_cid == ""
        parsed = json.loads(env.canonical_bytes.decode("utf-8"))
        assert parsed["header"]["kind"] == "implication"
        # input_cids sorted lex
        assert parsed["header"]["inputCids"] == sorted(
            ["blake3-512:acid", "blake3-512:bcid"]
        )


# ---------------------------------------------------------------------------
# compute_contract_set_cid edge cases
# ---------------------------------------------------------------------------


class TestContractSetCid:
    def test_empty_set_is_hash_of_empty_array(self):
        got = compute_contract_set_cid([])
        expected = blake3_512_of(b"[]")
        assert got == expected

    def test_singleton_set(self):
        got = compute_contract_set_cid(["blake3-512:aa"])
        expected = blake3_512_of(b'["blake3-512:aa"]')
        assert got == expected

    def test_duplicates_are_preserved(self):
        """The set CID is a function of the sorted sequence; duplicates
        in the input affect the output. (The spec treats this as a
        sequence-of-cids, not a deduplicated set.)"""
        a = compute_contract_set_cid(["blake3-512:aa"])
        b = compute_contract_set_cid(["blake3-512:aa", "blake3-512:aa"])
        # If callers want deduplication, they must do it before calling.
        assert a != b
