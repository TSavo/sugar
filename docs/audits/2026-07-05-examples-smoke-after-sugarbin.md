# Examples Smoke Gate Audit - 2026-07-05

Current base: `700020c92` (`origin/main` during the sweep).

This audit promotes the examples sweep into a permanent ratchet while defusing the signup-service landmine:

- `make examples-gate` is the smoke gate and discovers only `examples/*/run.sh`.
- `examples/signup-service/prove.sh` is an extended dependency-corpus proof sweep, not smoke; it is reachable only through `make examples-gate-extended`.
- A planted tooth asserts smoke discovery cannot include `examples/signup-service/prove.sh`.

Smoke result: 61 scripts; 3 GREEN; 58 NAMED_RED; 0 unclassified.
Extended result: 1 script; 1 GREEN; 0 NAMED_RED.

## Smoke Table

| example | rc | seconds | expectation | shape | issue |
| --- | ---: | ---: | --- | --- | --- |
| `examples/base64-showcase/run.sh` | 101 | 137.0 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/bitflags-showcase/run.sh` | 1 | 87.3 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/build-witness-showcase/run.sh` | 1 | 9.5 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/forall-loop-showcase/run.sh` | 1 | 19.2 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/forall-vampire-showcase/run.sh` | 1 | 78.5 | NAMED_RED | `mint-missing/forall-vampire-claim-rows` | #3579 |
| `examples/itertools-showcase/run.sh` | 1 | 124.9 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/itsdangerous-token-padding/run.sh` | 1 | 44.6 | NAMED_RED | `mint-missing/base64-decode-property-rows` | #3578 |
| `examples/java-abs-bound/run.sh` | 1 | 112.5 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-abs-flagship/run.sh` | 1 | 25.3 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-abs-model/run.sh` | 1 | 24.5 | NAMED_RED | `missing-universe-atom/int32-eq-bv-expr` | #3580 |
| `examples/java-abs-universe/run.sh` | 1 | 26.2 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-assertion-consistency/run.sh` | 1 | 30.3 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-b64-strong/run.sh` | 1 | 42.2 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-b64-tails/run.sh` | 1 | 29.3 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-bound-federation/run.sh` | 1 | 28.6 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-callbind-consistency/run.sh` | 1 | 29.0 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-codec-universe/run.sh` | 1 | 34.6 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-commons-codec-crc32/run.sh` | 1 | 34.7 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-crc32-universe/run.sh` | 1 | 42.1 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-crc32-valuepin/run.sh` | 1 | 43.0 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-forall-loop/run.sh` | 1 | 68.5 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-instance-universe/run.sh` | 1 | 23.2 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-mt-reference/run.sh` | 1 | 94.0 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-mt-strong/run.sh` | 0 | 80.3 | GREEN | `` |  |
| `examples/java-panama-bridge/run.sh` | 1 | 95.5 | NAMED_RED | `kit-transform/callsite-line-null` | #3607 |
| `examples/java-pattern-regex/run.sh` | 1 | 78.1 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-testng-consistency/run.sh` | 1 | 23.3 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-urlsafe-seam/run.sh` | 1 | 35.3 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-voltron/run.sh` | 1 | 37.1 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/java-witness-recompute/run.sh` | 1 | 27.8 | NAMED_RED | `prove-output/empty-json-receipt` | #3582 |
| `examples/num-integer-showcase/run.sh` | 1 | 124.0 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/numpy-attribute-safety-showcase/run.sh` | 1 | 104.5 | NAMED_RED | `prove-output/no-json-report` | #3583 |
| `examples/numpy-consumer-demo/run.sh` | 0 | 24.0 | GREEN | `` |  |
| `examples/numpy-showcase/run.sh` | 1 | 112.3 | NAMED_RED | `durable-row-missing/scientific-python-showcase` | #3576 |
| `examples/numpy-vendor/run.sh` | 1 | 54.8 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/pandas-showcase/run.sh` | 1 | 43.1 | NAMED_RED | `durable-row-missing/scientific-python-showcase` | #3576 |
| `examples/pandas-source-accounting/run.sh` | 1 | 34.3 | NAMED_RED | `audit-missing/pandas-package-audit` | #3575 |
| `examples/polars-showcase/run.sh` | 1 | 106.4 | NAMED_RED | `kit-transform/callsite-line-null` | #3607 |
| `examples/python-base64-federation/run.sh` | 1 | 76.3 | NAMED_RED | `verdict-drift/expected-proven-label` | #3589 |
| `examples/python-bodyguard-precondition/run.sh` | 101 | 175.4 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/python-guard-shapes/run.sh` | 0 | 44.3 | GREEN | `` |  |
| `examples/python-literal-base20/run.sh` | 1 | 70.8 | NAMED_RED | `verdict-drift/refused-row-expectation` | #3591 |
| `examples/python-literal-base64/run.sh` | 1 | 96.4 | NAMED_RED | `verdict-drift/refused-row-expectation` | #3591 |
| `examples/python-urlsafe-seam/run.sh` | 1 | 16.2 | NAMED_RED | `plugin-entrypoint/stale-python-lsp-module` | #3581 |
| `examples/regex-showcase/run.sh` | 1 | 153.2 | NAMED_RED | `prove-refused/expected-discharge-rows` | #3585 |
| `examples/rust-coretests-report/run.sh` | 1 | 1757.8 | NAMED_RED | `rust-lift-panic/chained-comparison` | #3588 |
| `examples/rust-regex-membership/run.sh` | 1 | 22.8 | NAMED_RED | `mint-output/regex-membership-ended-during-mint` | #3608 |
| `examples/rust-test-assertion-consistency/run.sh` | 1 | 26.0 | NAMED_RED | `kit-transform/callsite-line-null` | #3607 |
| `examples/rust-witness-showcase/run.sh` | 1 | 103.2 | NAMED_RED | `prove-refused/expected-discharge-rows` | #3585 |
| `examples/semver-showcase/run.sh` | 1 | 66.4 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/serde-json-showcase/run.sh` | 101 | 4.4 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/sklearn-showcase/run.sh` | 1 | 60.8 | NAMED_RED | `durable-row-missing/scientific-python-showcase` | #3576 |
| `examples/std-core-bodyguard-precondition/run.sh` | 101 | 52.4 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/std-core-showcase/run.sh` | 101 | 74.8 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/std-core-string-predicates/run.sh` | 1 | 73.0 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/tokio-await-implication-edge/run.sh` | 101 | 53.9 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/tokio-channel-implication-edge/run.sh` | 101 | 10.9 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/tokio-effect-consistency/run.sh` | 1 | 63.7 | NAMED_RED | `kit-transform/callsite-line-null` | #3607 |
| `examples/tokio-mutex-implication-edge/run.sh` | 101 | 15.4 | NAMED_RED | `build-failed/sugar-walk-bridge-source-symbol` | #3606 |
| `examples/url-showcase/run.sh` | 1 | 33.2 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |
| `examples/uuid-showcase/run.sh` | 1 | 19.7 | NAMED_RED | `prove-refused/provenance-kind-required` | #3587 |

## Extended Table

| example | rc | seconds | expectation | grounds |
| --- | ---: | ---: | --- | --- |
| `examples/signup-service/prove.sh` | 0 | 939.5 | GREEN | script exited 0 in the current examples gate sweep |

## Shape Buckets

| shape | count | issue | representatives |
| --- | ---: | --- | --- |
| `audit-missing/pandas-package-audit` | 1 | #3575 | `examples/pandas-source-accounting/run.sh` |
| `build-failed/sugar-walk-bridge-source-symbol` | 8 | #3606 | `examples/base64-showcase/run.sh`, `examples/python-bodyguard-precondition/run.sh`, `examples/serde-json-showcase/run.sh`, `examples/std-core-bodyguard-precondition/run.sh`, `examples/std-core-showcase/run.sh` |
| `durable-row-missing/scientific-python-showcase` | 3 | #3576 | `examples/numpy-showcase/run.sh`, `examples/pandas-showcase/run.sh`, `examples/sklearn-showcase/run.sh` |
| `kit-transform/callsite-line-null` | 4 | #3607 | `examples/java-panama-bridge/run.sh`, `examples/polars-showcase/run.sh`, `examples/rust-test-assertion-consistency/run.sh`, `examples/tokio-effect-consistency/run.sh` |
| `mint-missing/base64-decode-property-rows` | 1 | #3578 | `examples/itsdangerous-token-padding/run.sh` |
| `mint-missing/forall-vampire-claim-rows` | 1 | #3579 | `examples/forall-vampire-showcase/run.sh` |
| `mint-output/regex-membership-ended-during-mint` | 1 | #3608 | `examples/rust-regex-membership/run.sh` |
| `missing-universe-atom/int32-eq-bv-expr` | 1 | #3580 | `examples/java-abs-model/run.sh` |
| `plugin-entrypoint/stale-python-lsp-module` | 1 | #3581 | `examples/python-urlsafe-seam/run.sh` |
| `prove-output/empty-json-receipt` | 20 | #3582 | `examples/java-abs-bound/run.sh`, `examples/java-abs-flagship/run.sh`, `examples/java-abs-universe/run.sh`, `examples/java-assertion-consistency/run.sh`, `examples/java-b64-strong/run.sh` |
| `prove-output/no-json-report` | 1 | #3583 | `examples/numpy-attribute-safety-showcase/run.sh` |
| `prove-refused/expected-discharge-rows` | 2 | #3585 | `examples/regex-showcase/run.sh`, `examples/rust-witness-showcase/run.sh` |
| `prove-refused/provenance-kind-required` | 10 | #3587 | `examples/bitflags-showcase/run.sh`, `examples/build-witness-showcase/run.sh`, `examples/forall-loop-showcase/run.sh`, `examples/itertools-showcase/run.sh`, `examples/num-integer-showcase/run.sh` |
| `rust-lift-panic/chained-comparison` | 1 | #3588 | `examples/rust-coretests-report/run.sh` |
| `verdict-drift/expected-proven-label` | 1 | #3589 | `examples/python-base64-federation/run.sh` |
| `verdict-drift/refused-row-expectation` | 2 | #3591 | `examples/python-literal-base20/run.sh`, `examples/python-literal-base64/run.sh` |

## Representative Excerpts

### `audit-missing/pandas-package-audit` (#3575)

Representative: `examples/pandas-source-accounting/run.sh`

```
_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=1 vendor_conjoins=0
2026-07-05T21:47:00.778822Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_strip_sidecar_clone" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=1 vendor_conjoins=0
2026-07-05T21:47:00.779013Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_address_canonical_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=1 vendor_conjoins=0
2026-07-05T21:47:00.779145Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=1 vendor_conjoins=0
2026-07-05T21:47:00.779262Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=1 vendor_conjoins=0
FAIL: expected one pandas package audit, got 0
```

### `build-failed/sugar-walk-bridge-source-symbol` (#3606)

Representative: `examples/base64-showcase/run.sh`

```
    |
743 -             discharge_policy,
744 -         } = contract;
743 +             discharge_policy, bridge_source_symbol: _ } = contract;
    |
help: or always ignore missing fields here
    |
743 -             discharge_policy,
744 -         } = contract;
743 +             discharge_policy, .. } = contract;
    |
error[E0063]: missing field `bridge_source_symbol` in initializer of `RustVendorContractBindingMember`
   --> sugar-walk/src/bin/walk_rpc.rs:885:13
    |
885 |     Ok(Some(RustVendorContractBindingMember {
    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ missing `bridge_source_symbol`
Some errors have detailed explanations: E0027, E0063, E0573.
For more information about an error, try `rustc --explain E0027`.
error: could not compile `sugar-walk` (bin "sugar-walk-rpc") due to 3 previous errors
warning: build failed, waiting for other jobs to finish...
```

### `durable-row-missing/scientific-python-showcase` (#3576)

Representative: `examples/numpy-showcase/run.sh`

```
      {
        "witnessCid": "blake3-512:c9d18aec0f4c8534e72e880e3684002566b384b987073cdc736a798db1e01f75804c8ab26fe06134d1e1ee4a87e593eb69cc2b12d8e556152490754bfba3cd29",
        "verdict": "verified",
        "checks": [
          "signature",
          "content-address:package"
        ],
        "reason": "oracle resolved via package; rust recomputed the CID and it matched"
      }
    ],
    "total": 1,
    "ok": true
  },
  "ok": false
}
  ok: durable verify refused the expected degenerate twin (exit 1)
  MISSING: durable verify preserves good rot90 discharge (consistent about callsite .test_rot90_quarter_turn)
  MISSING: durable verify preserves contradiction refusal (contradictory about callsite .test_rot90_contradiction)
  ok: durable verify recomputes witness package
FAIL: sugar did not produce the expected verdict.
```

### `kit-transform/callsite-line-null` (#3607)

Representative: `examples/java-panama-bridge/run.sh`

```
oins=0
2026-07-05T21:35:29.213421Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_strip_sidecar_clone" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=3 source_audits=1 factory_audits=5 assertion_surface_audits=1 source_mementos=2 call_edges=2 vendor_conjoins=0
2026-07-05T21:35:29.218163Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_address_canonical_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=3 source_audits=1 factory_audits=5 assertion_surface_audits=1 source_mementos=2 call_edges=2 vendor_conjoins=0
2026-07-05T21:35:29.218585Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=3 source_audits=1 factory_audits=5 assertion_surface_audits=1 source_mementos=2 call_edges=2 vendor_conjoins=0
2026-07-05T21:35:29.219705Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=3 source_audits=1 factory_audits=5 assertion_surface_audits=1 source_mementos=2 call_edges=2 vendor_conjoins=0
[1m[31merror[39m[0m: kit transform failed: bridge `call:decoded_len_estimate`: callsite.line must be an integer, got null
```

### `mint-missing/base64-decode-property-rows` (#3578)

Representative: `examples/itsdangerous-token-padding/run.sh`

```
ugar_verifier::enumerate_callsites: enumerate_callsites: scanning contracts for callsites mementos=69 bridges=0
2026-07-05T21:21:03.548862Z  INFO enumerate_callsites: sugar_verifier::enumerate_callsites: enumerate_callsites: complete callsites=0
2026-07-05T21:21:03.557185Z  INFO sugar_verifier::runner: verifier: contract self-post pass complete self_posts=0 self_post_reflexive=0 self_post_substantive=0 self_post_undecidable=0
2026-07-05T21:21:03.560812Z  INFO sugar_verifier::consistency: verifier/ambient: universals will be conjoined into every obligation candidates=16 ambient_foralls=0 ambient_ground_callsite_facts=4
2026-07-05T21:21:03.560893Z  INFO sugar_verifier::consistency: verifier/linker: contract posts will be specialized into matching obligations candidates=16 ambient_posts=0
2026-07-05T21:21:03.565559Z  INFO sugar_verifier::consistency: verifier: test-assertion consistency pass complete candidates=16 consistent=0 contradictory=1 undecidable=0 witnessed=0
2026-07-05T21:21:03.576847Z  INFO load_all_proofs{root=.}: sugar_verifier::load_all_proofs: load_all_proofs: scanning for .proof files root=.
2026-07-05T21:21:03.613907Z  INFO load_all_proofs{root=.}: sugar_verifier::load_all_proofs: load_all_proofs: complete mementos=77 load_errors=0
rows(bad):
  refused        consistency:itsdangerous.encoding.base64_encode#euf#c:call:itsdangerous.encoding.base64_encode(c:python:bytes(
FAIL(bad): no base64_decode property rows in receipt
==== itsdangerous-token-padding: FAIL ====
```

### `mint-missing/forall-vampire-claim-rows` (#3579)

Representative: `examples/forall-vampire-showcase/run.sh`

```
sugarbin: local target skipped: stale binary /Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/target/release/sugar has stamp b99dc4aa269799065515a21892538c4aa8ee2eeb-dirty-00a1dbcdc1210f94, need blake3-512:665495b208517fed02c99f86092f053e672123a697bb0043a834846d97316f1dbe70a4a135122aa0a9b2f3747b332f994c62a48b9c01cd983540ff3438b3aeba
2026-07-05T21:18:15.868092Z  INFO load_all_proofs{root=.}: sugar_verifier::load_all_proofs: load_all_proofs: scanning for .proof files root=.
2026-07-05T21:18:15.876857Z  INFO load_all_proofs{root=.}: sugar_verifier::load_all_proofs: load_all_proofs: complete mementos=2 load_errors=0
2026-07-05T21:18:15.877549Z  INFO enumerate_callsites: sugar_verifier::enumerate_callsites: enumerate_callsites: scanning contracts for callsites mementos=2 bridges=0
2026-07-05T21:18:15.878168Z  INFO enumerate_callsites: sugar_verifier::enumerate_callsites: enumerate_callsites: complete callsites=0
FAIL: missing forall-vampire claim row(s): forall_vampire_good_right_identity, forall_vampire_bad_false_universal; available rows: <none>
```

### `mint-output/regex-membership-ended-during-mint` (#3608)

Representative: `examples/rust-regex-membership/run.sh`

```
SCOPE: RegexSugar — a rust regex-match assertion lifted to z3 regex theory (str.in_re).
SCOPE: re.is_match(s) ⟺ str.in_re(s, R); the pattern literal lowers to a z3 RegLan term.
SCOPE: COMPOSITIONAL pattern operand (inline literal / const-string / concat!); format! bails as the frontier.
SCOPE: SAME ProofIR atom as the Java @Pattern pass — str.in-regex(subject, raw-regex); meet by CID.
SCOPE: GOOD: matching subjects -> str.in_re SAT -> discharged.
SCOPE: BAD: a non-matching subject -> str.in_re UNSAT -> refused (membership teeth).
SCOPE: NONREGULAR: backref/lookahead refused BY NAME at lift time; no str.in-regex row, the floor stands.
== build the CLI + rust test-assertion lifter ==
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1.48s
==================== suite: good (expect DISCHARGE) ====================
-- mint: lift regex-match assertions -> str.in-regex membership rows --
```

### `missing-universe-atom/int32-eq-bv-expr` (#3580)

Representative: `examples/java-abs-model/run.sh`

```
 local target skipped: stale binary /Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/target/release/sugar has stamp b99dc4aa269799065515a21892538c4aa8ee2eeb-dirty-00a1dbcdc1210f94, need blake3-512:665495b208517fed02c99f86092f053e672123a697bb0043a834846d97316f1dbe70a4a135122aa0a9b2f3747b332f994c62a48b9c01cd983540ff3438b3aeba
SCOPE: java-abs-model — z3.model derive showcase, chain closed end to end.
SCOPE: vendor Math.java -> kit walk -> minted .proof -> extract bv_tree -> z3.model derive.
SCOPE: Walked body: (a < 0) ? -a : a  =>  bv32.ite(bv32.slt(a,0), bv32.neg(a), a).
SCOPE: Input: Integer.MIN_VALUE = -2147483648 = #x80000000.
SCOPE: NO hardcoded formula: the bv_tree only ever comes from the lifted universe.
== resolve the sugar CLI ==
   sugar binary: /Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_665495b208517fed02c99f86092f053e672123a697bb0043a834846d97316f1dbe70a4a135122aa0a9b2f3747b332f994c62a48b9c01cd983540ff3438b3aeba
== build the Java kit ==
   kit class: /Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/java/sugar-lift-java-tests/out/JavaTestAssertionsRpc.class
== prepare manifest and clean state ==
== 1. mint: lift Math.java -> int32.eq-bv-expr universe atom ==
   minted: blake3-512_2af30cb74c652e439294d4930a2e25305ef5840edd22a2068525664d4b3bf7b3eedef712661af7495201563fd9ac98e43ab37409972ef7447b17e6e248f7e799.proof
FAIL: minted .proof carries no int32.eq-bv-expr universe atom
```

### `plugin-entrypoint/stale-python-lsp-module` (#3581)

Representative: `examples/python-urlsafe-seam/run.sh`

```
 (expect: refused) ====================
2026-07-05T21:56:53.203320Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.before_dispatch" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:56:53.207893Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="read_response.before_read_line" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
/usr/local/opt/python@3.14/bin/python3.14: No module named sugar_lift_py_tests.lsp
2026-07-05T21:56:54.052058Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="read_response.after_read_line" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
[1m[31merror[39m[0m: kit transform failed: lift plugin diagnostic kind=transport frontend=sugar-cli::lift_plugin input_format=lift-plugin-json-rpc-v1 path=lift-plugin.transport: lift plugin closed stdout before responding; fix=Inspect the lifter command, stdout/stderr, and JSON-RPC framing; keep failures as LiftPluginDiagnosticPayload, not a bare string.
FAIL: mint (bad)
==== python-urlsafe-seam: FAIL ====
```

### `prove-output/empty-json-receipt` (#3582)

Representative: `examples/java-abs-bound/run.sh`

```
l:abs(MIN), bv32.ite(bv32.slt(a,0),bv32.neg(a),a))
SCOPE: G2b bound:   >=(call:abs(MIN), 0)  → int32.gte-const via bv32 contagion
SCOPE: Conjoined: bv32 evaluates abs(MIN)=-2^31; bvsge(-2^31, #x00000000) = false.
SCOPE: UNSAT → unsatisfied. No vendor test needed — the walked body adjudicates it.
== build the sugar CLI ==
   Compiling libsugar v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/libsugar)
   Compiling sugar-verifier v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-verifier)
   Compiling sugar-walk v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-walk)
   Compiling sugar-lift v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-lift)
   Compiling sugar-linker v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-linker)
   Compiling sugar-cli v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-cli)
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 1m 24s
== build the Java kit ==
== prepare manifest and clean state ==
── suite: bad ──
-- mint --
   int32.eq-bv-expr universe row present (walked Math.abs body)
-- prove --
/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/examples/java-abs-bound/bad/.prove.json: expected JSON receipt, got non-JSON output: <empty output>
```

### `prove-output/no-json-report` (#3583)

Representative: `examples/numpy-attribute-safety-showcase/run.sh`

```
0m15568 [3mrss_available[0m[2m=[0mtrue [3mrss_delta_kib[0m[2m=[0m0 [3mline_bytes[0m[2m=[0m0 [3mcontracts[0m[2m=[0m2 [3msource_audits[0m[2m=[0m0 [3mfactory_audits[0m[2m=[0m0 [3massertion_surface_audits[0m[2m=[0m0 [3msource_mementos[0m[2m=[0m0 [3mcall_edges[0m[2m=[0m0 [3mvendor_conjoins[0m[2m=[0m0
[2m2026-07-05T21:42:34.094542Z[0m [32m INFO[0m [2mlibsugar::core::lift_plugin[0m[2m:[0m lift-plugin transport memory checkpoint [3mstage[0m[2m=[0m"claim_from_response_term.after_lift_response_contract" [3mrss_kib[0m[2m=[0m15568 [3mrss_available[0m[2m=[0mtrue [3mrss_delta_kib[0m[2m=[0m0 [3mline_bytes[0m[2m=[0m0 [3mcontracts[0m[2m=[0m2 [3msource_audits[0m[2m=[0m0 [3mfactory_audits[0m[2m=[0m0 [3massertion_surface_audits[0m[2m=[0m0 [3msource_mementos[0m[2m=[0m0 [3mcall_edges[0m[2m=[0m0 [3mvendor_conjoins[0m[2m=[0m0
[2m2026-07-05T21:42:34.094556Z[0m [32m INFO[0m [2mlibsugar::core::lift_plugin[0m[2m:[0m lift-plugin transport memory checkpoint [3mstage[0m[2m=[0m"parse_session.after_claim_from_response_term" [3mrss_kib[0m[2m=[0m15568 [3mrss_available[0m[2m=[0mtrue [3mrss_delta_kib[0m[2m=[0m0 [3mline_bytes[0m[2m=[0m0 [3mcontracts[0m[2m=[0m2 [3msource_audits[0m[2m=[0m0 [3mfactory_audits[0m[2m=[0m0 [3massertion_surface_audits[0m[2m=[0m0 [3msource_mementos[0m[2m=[0m0 [3mcall_edges[0m[2m=[0m0 [3mvendor_conjoins[0m[2m=[0m0
good: no JSON report found
```

### `prove-refused/expected-discharge-rows` (#3585)

Representative: `examples/regex-showcase/run.sh`

```
lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_address_canonical_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:59:15.915253Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:59:15.915545Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
-- prove: consistency rows plus witness-package row --
   consistency statuses: refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused
   witness-package status: refused
FAIL[good]: expected all consistency rows discharged, got refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused
```

### `prove-refused/provenance-kind-required` (#3587)

Representative: `examples/bitflags-showcase/run.sh`

```
=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:16:23.326696Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_address_canonical_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:16:23.327175Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:16:23.327480Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
-- prove: consistency rows plus witness-package row --
   prove consistency statuses: refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused,refused
   prove witness-package status: refused
FAIL[good]: expected witness discharge, got refused
```

### `rust-lift-panic/chained-comparison` (#3588)

Representative: `examples/rust-coretests-report/run.sh`

```
mentations/rust/sugar-walk)
   Compiling sugar-lift v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-lift)
   Compiling sugar-linker v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-linker)
   Compiling sugar-lift-rust-tests v0.1.0 (/Users/tsavo/provekit/.worktrees/examples-smoke-after-sugarbin/implementations/rust/sugar-lift-rust-tests)
    Finished `release` profile [optimized] target(s) in 29m 10s
== lift --report over 140 coretests files ==
== honest source ledger ==
MEASUREMENT FAILED: no source-audit headline emitted. Cause (stderr tail):
thread 'main' (132821740) panicked at sugar-lift-rust-tests/src/sugar/for_replay.rs:1299:38:
comparison operators cannot be chained
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
2026-07-05T22:28:45.064697Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="read_response.after_read_line" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=0 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
error: lift plugin diagnostic kind=transport frontend=sugar-cli::lift_plugin input_format=lift-plugin-json-rpc-v1 path=lift-plugin.transport: lift plugin closed stdout before responding; fix=Inspect the lifter command, stdout/stderr, and JSON-RPC framing; keep failures as LiftPluginDiagnosticPayload, not a bare string.
```

### `verdict-drift/expected-proven-label` (#3589)

Representative: `examples/python-base64-federation/run.sh`

```
om_response_term.after_strip_sidecar_clone" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:50:07.997274Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_address_canonical_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:50:07.997514Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:50:07.997708Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
  consumer conjoin row: unsatisfied  test assertions contradictory about callsite `b64vendor.encodeBase64#euf#c:call:b64vendor.encodeBase64(s:'xyz'
  totals: discharged=1 violations=1
OK(bad): expected REFUSED
==== python-base64-federation: FAIL ====
```

### `verdict-drift/refused-row-expectation` (#3591)

Representative: `examples/python-literal-base20/run.sh`

```
ges=0 vendor_conjoins=0
2026-07-05T21:54:54.897687Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="claim_from_response_term.after_lift_response_contract" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
2026-07-05T21:54:54.897768Z  INFO libsugar::core::lift_plugin: lift-plugin transport memory checkpoint stage="parse_session.after_claim_from_response_term" rss_kib=0 rss_available=false rss_delta_kib=0 line_bytes=0 contracts=2 source_audits=0 factory_audits=0 assertion_surface_audits=0 source_mementos=0 call_edges=0 vendor_conjoins=0
rows(bad):
  prove assertion   unsatisfied  test assertions contradictory about callsite `encode20#euf#c:call:encode20(s:'A')::assertion` [solver 'z3' returned unsat (obligat
  prove witness     refused      consistency check refused: contract `witness-package:blake3-512:ad0cc97c361e0e1dd71f3d57998162c585ccf4eebe128fe187743ddfb020797ebd
  verify assertion  unsatisfied  test assertions contradictory about callsite `encode20#euf#c:call:encode20(s:'A')::assertion` [solver 'z3' returned unsat (obligat
  verify witness    refused      consistency check refused: contract `witness-package:blake3-512:ad0cc97c361e0e1dd71f3d57998162c585ccf4eebe128fe187743ddfb020797ebd
  witness dimension total=1 ok=True verdicts=['verified']
FAIL(bad): expected refused rows
==== python-literal-base20: FAIL ====
```
