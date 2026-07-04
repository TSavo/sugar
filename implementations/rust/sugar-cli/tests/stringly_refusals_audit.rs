// SPDX-License-Identifier: Apache-2.0
//
// IDD instrument for #3482.
//
// The final synthesis for the effects migration is not "delete refusal".
// Refused-not-green remains load-bearing; the stringly shape dies. A refusal
// ground should become a typed effect variant carrying its evidence
// (InsufficientEvidence, NoSiblingToContradict, UnwitnessedDischarge, ...),
// and callers should exhaustively match that variant instead of parsing prose.
//
// This frontier pins today's stringly refusal EMISSION sites across the Rust
// and Python kits. It intentionally does not migrate anything; it names the
// current R vector so follow-up PRs ratchet it down and new "status=refused +
// reason prose" sites cannot appear quietly.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Site {
    ground: String,
    path: String,
    line: usize,
    text: String,
}

#[derive(Debug, Clone)]
struct ExpectedSite {
    ground: &'static str,
    path: &'static str,
    line: usize,
    needle: &'static str,
    replacement: &'static str,
}

const EXPECTED_STRINGLY_REFUSAL_EMISSIONS: &[ExpectedSite] = &[
    ExpectedSite { ground: "body-reduction-refusal-effect", path: "implementations/rust/sugar-verifier/src/body_discharge.rs", line: 452, needle: "Err(WpError::Refused(r)) => {", replacement: "BodyReductionEffect::{WpRefused,PreconditionMissing} carrying callee and WP ground" },
    ExpectedSite { ground: "body-reduction-refusal-effect", path: "implementations/rust/sugar-verifier/src/body_discharge.rs", line: 1028, needle: "Err(WpError::Refused(r)) => {", replacement: "BodyReductionEffect::{WpRefused,PreconditionMissing} carrying callee and WP ground" },
    ExpectedSite { ground: "component-plan-decline-effect", path: "implementations/rust/sugar-cli/src/component_plan.rs", line: 1064, needle: "decline.reason = Some(\"component refused workspace\".to_string());", replacement: "ComponentPlanEffect::Declined/Refused with component identity and manifest path" },
    ExpectedSite { ground: "composition-effect-mismatch", path: "implementations/rust/sugar-cli/src/cmd_compose.rs", line: 317, needle: "return Err(RpcError::refused_with_atom(", replacement: "CompositionEffect::EffectSetMismatch carrying atom CID and parameter index" },
    ExpectedSite { ground: "composition-refusal-effect", path: "implementations/rust/libsugar/src/ffi.rs", line: 251, needle: "ComposeRefused(CompositionRefusalMemento),", replacement: "CompositionEffect variant from CompositionRefusalMemento header kind" },
    ExpectedSite { ground: "composition-refusal-effect", path: "implementations/rust/libsugar/src/ffi.rs", line: 270, needle: "FfiError::ComposeRefused(refusal) => {", replacement: "CompositionEffect variant from CompositionRefusalMemento header kind" },
    ExpectedSite { ground: "composition-refusal-effect", path: "implementations/rust/libsugar/src/ffi.rs", line: 389, needle: "let composed = compose_chain_contracts(&steps).map_err(FfiError::ComposeRefused)?;", replacement: "CompositionEffect variant from CompositionRefusalMemento header kind" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 1572, needle: "_ => panic!(\"sugar-walk RPC pat_single_ident refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 1726, needle: "panic!(\"sugar-walk RPC mutex_guard_access_lock_site refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 1781, needle: "_ => panic!(\"sugar-walk RPC mutex_lock_site refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 3450, needle: "Err(err) => panic!(\"sugar-walk refused unserializable lifted call actual term: {err}\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 3577, needle: "_ => panic!(\"sugar-walk RPC expr_type_identity refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4354, needle: "_ => panic!(\"sugar-walk RPC pat_ident_name refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4380, needle: "_ => panic!(\"sugar-walk RPC pat_immutable_ident_name refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4417, needle: "_ => panic!(\"sugar-walk RPC pat_type_identity refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4527, needle: "_ => panic!(\"sugar-walk RPC expr_return_crate refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4636, needle: "_ => panic!(\"sugar-walk RPC call_expr_callee refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4709, needle: "_ => panic!(\"sugar-walk RPC expr_as_call refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 4905, needle: "_ => panic!(\"sugar-walk RPC expr_path_text refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 5183, needle: "_ => panic!(\"sugar-walk RPC expr_bare_ident_name refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 8383, needle: "Err(err) => panic!(\"sugar-walk refused unserializable evidence predicate: {err}\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 9308, needle: "_ => panic!(\"sugar-walk RPC operand_symbol refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10032, needle: "_ => panic!(\"sugar-walk RPC expr_sort refused unknown syn::Lit variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10057, needle: "_ => panic!(\"sugar-walk RPC expr_sort refused unknown syn::UnOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10093, needle: "_ => panic!(\"sugar-walk RPC expr_sort refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10143, needle: "_ => panic!(\"sugar-walk RPC binary_result_sort refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10182, needle: "_ => panic!(\"sugar-walk RPC sort_from_type refused unknown syn::Type variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10228, needle: "_ => panic!(\"sugar-walk RPC binary_operator_name refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10240, needle: "_ => panic!(\"sugar-walk RPC unary_operator_name refused unknown syn::UnOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10334, needle: "panic!(\"sugar-walk refused integer literal outside canonical i128 floor: {err}\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 10449, needle: "panic!(\"sugar-walk refused local op CID canonicalization for `{operator}`: {err}\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/contract.rs", line: 380, needle: "_ => panic!(\"sugar-walk contract refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 831, needle: "_ => panic!(\"sugar-walk emit find_term_function refused unknown syn::Item variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 899, needle: "_ => panic!(\"sugar-walk emit ffi collector refused unknown syn::Item variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 979, needle: "_ => panic!(\"sugar-walk emit proc-macro collector refused unknown syn::Item variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 1552, needle: "_ => panic!(\"sugar-walk emit receiver source refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 1602, needle: "_ => panic!(\"sugar-walk emit mutable borrow source refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2275, needle: "_ => panic!(\"sugar-walk emit expr_sort refused unknown syn::Lit variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2299, needle: "_ => panic!(\"sugar-walk emit expr_sort refused unknown syn::UnOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2350, needle: "_ => panic!(\"sugar-walk emit expr_sort refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2378, needle: "_ => panic!(\"sugar-walk emit logical op refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2402, needle: "_ => panic!(\"sugar-walk emit comparison op refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2426, needle: "_ => panic!(\"sugar-walk emit arithmetic op refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2450, needle: "_ => panic!(\"sugar-walk emit bitwise op refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2502, needle: "_ => panic!(\"sugar-walk emit sort_from_type refused unknown syn::Type variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2579, needle: "_ => panic!(\"sugar-walk emit concept_sort refused unknown syn::Type variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2640, needle: "_ => panic!(\"sugar-walk emit partial_return_loss refused unknown syn::Type variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/emit.rs", line: 2739, needle: "_ => panic!(\"sugar-walk emit local_pat_type refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 986, needle: "panic!(\"sugar-walk pattern name collector refused opaque syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 990, needle: "panic!(\"sugar-walk pattern name collector refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1254, needle: "panic!(\"sugar-walk len receiver classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1258, needle: "panic!(\"sugar-walk len receiver classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1311, needle: "panic!(\"sugar-walk root identifier classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1319, needle: "Err(err) => panic!(\"sugar-walk refused unserializable IR term key: {err}\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1394, needle: "panic!(\"sugar-walk local binding classifier refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1541, needle: "panic!(\"sugar-walk assignment target collector refused opaque syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1545, needle: "panic!(\"sugar-walk assignment target collector refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1562, needle: "panic!(\"sugar-walk assignment target collector refused opaque statement macro\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1670, needle: "panic!(\"sugar-walk string literal classifier refused unknown syn::Lit variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1712, needle: "panic!(\"sugar-walk string literal classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1716, needle: "panic!(\"sugar-walk string literal classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 1817, needle: "panic!(\"sugar-walk token string literal classifier refused unknown syn::Lit variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2191, needle: "panic!(\"sugar-walk guarded panic collector refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2193, needle: "_ => panic!(\"sugar-walk guarded panic collector refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2261, needle: "panic!(\"sugar-walk pure-free guard collector refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2265, needle: "panic!(\"sugar-walk pure-free guard collector refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2618, needle: "panic!(\"sugar-walk keyset source classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2622, needle: "panic!(\"sugar-walk keyset source classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2667, needle: "panic!(\"sugar-walk local single-pattern classifier refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2694, needle: "panic!(\"sugar-walk single-pattern classifier refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2720, needle: "panic!(\"sugar-walk tuple-pattern classifier refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2819, needle: "panic!(\"sugar-walk method-call classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2823, needle: "panic!(\"sugar-walk method-call classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2914, needle: "panic!(\"sugar-walk call classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 2918, needle: "panic!(\"sugar-walk call classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3106, needle: "panic!(\"sugar-walk expression root collector refused opaque syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3110, needle: "panic!(\"sugar-walk expression root collector refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3126, needle: "panic!(\"sugar-walk expression root collector refused opaque statement macro\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3243, needle: "panic!(\"sugar-walk assignment root collector refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3247, needle: "panic!(\"sugar-walk assignment root collector refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3317, needle: "panic!(\"sugar-walk pattern binding collector refused opaque syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3321, needle: "panic!(\"sugar-walk pattern binding collector refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3369, needle: "panic!(\"sugar-walk pattern binder refused opaque syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3373, needle: "panic!(\"sugar-walk pattern binder refused unknown syn::Pat variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3613, needle: "_ => panic!(\"sugar-walk predicate classifier refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3789, needle: "panic!(\"sugar-walk receiver producer classifier refused unknown syn::Expr variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 3836, needle: "_ => panic!(\"sugar-walk term classifier refused unknown syn::Lit variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 4153, needle: "_ => panic!(\"sugar-walk term classifier refused unknown syn::BinOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 4178, needle: "_ => panic!(\"sugar-walk term classifier refused unknown syn::UnOp variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 4205, needle: "panic!(\"sugar-walk term classifier refused uninterpreted verbatim expression\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 4207, needle: "_ => panic!(\"sugar-walk term classifier refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/lift.rs", line: 4259, needle: "panic!(\"sugar-walk predicate operator classifier refused unknown syn::BinOp variant\")", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs", line: 352, needle: "_ => panic!(\"sugar-walk loop mutation collector refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs", line: 402, needle: "_ => panic!(\"sugar-walk loop assignment collector refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/source_oracle.rs", line: 1017, needle: "_ => panic!(\"sugar-walk source_oracle refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/source_oracle.rs", line: 1358, needle: "_ => panic!(\"sugar-walk source_oracle refused unknown syn::Item variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/type_decl.rs", line: 665, needle: "_ => panic!(\"sugar-walk type_decl refused unknown syn::Item variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/walk.rs", line: 557, needle: "_ => panic!(\"sugar-walk WP walker refused unknown syn::Expr variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "coverage-panic-wording", path: "implementations/rust/sugar-walk/src/walk.rs", line: 645, needle: "_ => panic!(\"sugar-walk WP pattern collector refused unknown syn::Pat variant\"),", replacement: "coverage ICE/panic with typed frontier owner; do not encode as refused prose" },
    ExpectedSite { ground: "outlives-region-refusal-effect", path: "implementations/rust/sugar-verifier/src/outlives.rs", line: 70, needle: "DischargeOutcome::Refused {", replacement: "VerifyEffect::OutlivesNotProvable{longer,shorter}" },
    ExpectedSite { ground: "outlives-region-refusal-effect", path: "implementations/rust/sugar-verifier/src/outlives.rs", line: 133, needle: "if matches!(caller_graph.check(a, b), DischargeOutcome::Refused { .. }) {", replacement: "VerifyEffect::OutlivesNotProvable{longer,shorter}" },
    ExpectedSite { ground: "path-composition-refusal-effect", path: "implementations/rust/libsugar/src/core/path_executor.rs", line: 166, needle: ".ok_or_else(|| PathExecutionError::Refused(Box::new(missing_kit_refusal(step))))?;", replacement: "CompositionEffect::MissingRequirement from PathExecutionError" },
    ExpectedSite { ground: "path-composition-refusal-effect", path: "implementations/rust/libsugar/src/core/path_executor.rs", line: 236, needle: "Err(PathExecutionError::Refused(Box::new(", replacement: "CompositionEffect::MissingRequirement from PathExecutionError" },
    ExpectedSite { ground: "path-composition-refusal-effect", path: "implementations/rust/libsugar/src/core/path_executor.rs", line: 344, needle: "PathExecutionError::Refused(Box::new(prove_not_supported_refusal(step)))", replacement: "CompositionEffect::MissingRequirement from PathExecutionError" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 757, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 780, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 785, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 828, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 867, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 879, needle: "raise _UnsupportedSyntax(node, \"while/else is refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 891, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 947, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1068, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1077, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1084, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1112, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1116, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1174, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1199, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1221, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1236, needle: "raise _UnsupportedSyntax(node.slice, \"slice annotations are refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1242, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1261, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1268, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1275, needle: "raise _UnsupportedSyntax(node, \"boolean operation without two operands\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1362, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1367, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1379, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1391, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1419, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1447, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1475, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1507, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1516, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1545, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1685, needle: "raise _UnsupportedSyntax(node, f\"unsupported constant: {type(value).__name__}\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1689, needle: "raise _UnsupportedSyntax(node, \"malformed comparison expression\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1695, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 1941, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2630, needle: "return _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2666, needle: "return _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2776, needle: "self._refuse(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2783, needle: "self._refuse(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2790, needle: "self._refuse(node, \"generators are refused\", kind=\"generator-refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2793, needle: "self._refuse(node, \"generators are refused\", kind=\"generator-refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2796, needle: "self._refuse(node, \"await expressions are refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2806, needle: "self.refused = _UnsupportedSyntax(node, reason, kind=kind)", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 2822, needle: "raise _UnsupportedSyntax(node, \"star imports are refused\")", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-unsupported-syntax-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/lifter.py", line: 3161, needle: "raise _UnsupportedSyntax(", replacement: "PythonLiftEffect variant for the refused syntax ground" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 32, needle: "VALUE_PIN_REFUSAL_KIND = \"value-pin-refused\"", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 33, needle: "ENUM_PIN_REFUSAL_KIND = \"enum-pin-refused\"", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 121, needle: "scan.refusals.append(_pin_refusal(candidate, refusal_reason))", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 126, needle: "scan.refusals.append(_pin_refusal(candidate, exc.reason))", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 211, needle: "_pin_refusal(", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 221, needle: "_pin_refusal(", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 230, needle: "_pin_refusal(", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "python-value-pin-effect", path: "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/value_pins.py", line: 240, needle: "scan.refusals.append(_pin_refusal(candidate, exc.reason))", replacement: "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason" },
    ExpectedSite { ground: "rust-walk-source-effect-status", path: "implementations/rust/sugar-walk/src/bin/walk_rpc.rs", line: 18467, needle: "\"status\": \"refused\",", replacement: "RustWalk source effect status variant with source ledger ground" },
    ExpectedSite { ground: "solver-batch-refusal-effect", path: "implementations/rust/sugar-verifier/src/solvers/batch.rs", line: 168, needle: "raw: ObligationVerdict::Refused,", replacement: "SolverEffect::BatchRefused carrying solver and job" },
    ExpectedSite { ground: "solver-unsupported-construct-effect", path: "implementations/rust/sugar-verifier/src/solvers/subprocess.rs", line: 211, needle: "ObligationVerdict::Refused,", replacement: "SolverEffect::UnsupportedConstruct{symbol}" },
    ExpectedSite { ground: "solver-unsupported-construct-effect", path: "implementations/rust/sugar-verifier/src/solvers/subprocess.rs", line: 225, needle: "} else if verdict == ObligationVerdict::Refused {", replacement: "SolverEffect::UnsupportedConstruct{symbol}" },
    ExpectedSite { ground: "wp-refusal-effect", path: "implementations/rust/libsugar/src/wp.rs", line: 139, needle: "pub enum Refusal {", replacement: "WpEffect::{OpaqueLoop,OpaqueCall} surfaced through typed evidence verdict" },
    ExpectedSite { ground: "wp-refusal-effect", path: "implementations/rust/libsugar/src/wp.rs", line: 1291, needle: "Err(WpError::Refused(_)) => Ok(EvidenceVerdict {", replacement: "WpEffect::{OpaqueLoop,OpaqueCall} surfaced through typed evidence verdict" },
];

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-cli has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn source_roots(root: &Path) -> Vec<PathBuf> {
    [
        "implementations/rust/sugar-verifier/src",
        "implementations/rust/sugar-cli/src",
        "implementations/rust/sugar-lift-rust-tests/src",
        "implementations/rust/sugar-walk/src",
        "implementations/rust/libsugar/src",
        "implementations/python/sugar-lift-py-tests/src",
        "implementations/python/sugar-lift-python-source/src",
    ]
    .into_iter()
    .map(|rel| root.join(rel))
    .collect()
}

fn source_files_under(root: &Path) -> Result<Vec<PathBuf>, String> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let entries = fs::read_dir(&dir).map_err(|err| format!("read {}: {err}", dir.display()))?;
        for entry in entries {
            let path = entry
                .map_err(|err| format!("read entry under {}: {err}", dir.display()))?
                .path();
            if path.is_dir() {
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if matches!(name, "target" | ".git" | "__pycache__") {
                    continue;
                }
                stack.push(path);
            } else if matches!(path.extension().and_then(|e| e.to_str()), Some("rs" | "py")) {
                out.push(path);
            }
        }
    }
    out.sort();
    Ok(out)
}

fn collect_stringly_refusal_emissions(root: &Path) -> Result<Vec<Site>, String> {
    let mut out = Vec::new();
    for source_root in source_roots(root) {
        for path in source_files_under(&source_root)? {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path).map_err(|err| format!("read {}: {err}", rel))?;
            out.extend(collect_stringly_refusal_emissions_from_source(
                &rel, &source,
            ));
        }
    }
    out.sort();
    Ok(out)
}

fn collect_stringly_refusal_emissions_from_source(path: &str, source: &str) -> Vec<Site> {
    let lines = source.lines().collect::<Vec<_>>();
    let mut out = Vec::new();
    let mut pending_cfg_test = false;
    let mut skipping_cfg_test = false;
    let mut test_depth: i64 = 0;

    for (idx, line) in lines.iter().enumerate() {
        let line_no = idx + 1;
        let trimmed = line.trim();
        if path.ends_with(".rs") {
            if skipping_cfg_test {
                test_depth += brace_delta(line);
                if test_depth <= 0 {
                    skipping_cfg_test = false;
                    test_depth = 0;
                }
                continue;
            }
            if trimmed.starts_with("#[cfg(test)]") {
                pending_cfg_test = true;
                continue;
            }
            if pending_cfg_test {
                if trimmed.starts_with("mod ") || trimmed.contains("mod tests") {
                    test_depth = brace_delta(line).max(1);
                    skipping_cfg_test = true;
                }
                if !trimmed.starts_with('#') {
                    pending_cfg_test = false;
                }
                continue;
            }
        }

        let context = context_window(&lines, idx);
        if let Some(ground) = classify_emission(path, trimmed, &context) {
            out.push(Site {
                ground: ground.to_string(),
                path: path.to_string(),
                line: line_no,
                text: trimmed.to_string(),
            });
        }
    }
    out
}

fn brace_delta(line: &str) -> i64 {
    line.chars().filter(|c| *c == '{').count() as i64
        - line.chars().filter(|c| *c == '}').count() as i64
}

fn context_window(lines: &[&str], idx: usize) -> String {
    let start = idx.saturating_sub(4);
    let end = (idx + 5).min(lines.len());
    lines[start..end].join("\n")
}

fn classify_emission(path: &str, line: &str, context: &str) -> Option<&'static str> {
    if line.is_empty()
        || line.starts_with("//")
        || line.starts_with("//!")
        || line.starts_with("///")
        || line.starts_with('*')
    {
        return None;
    }

    if is_python_unsupported_syntax_constructor(line) {
        return Some("python-unsupported-syntax-effect");
    }
    if path.contains("sugar_lift_python_source/value_pins.py") && is_value_pin_refusal(line) {
        return Some("python-value-pin-effect");
    }
    if path.contains("sugar_lift_py_tests/kit_rpc/effect_dto.py")
        && line.contains("status: str = \"refused\"")
    {
        return Some("python-kit-effect-dto-status");
    }
    if path.contains("sugar_lift_py_tests/lift_rpc.py")
        && (line.contains("def _source_refusal_status")
            || line.contains("\"status\": _source_refusal_status"))
    {
        return Some("python-source-oracle-effect");
    }
    if path.contains("sugar_lift_python_source/bind_rpc.py")
        && line.contains("\"outcome\": \"refused\"")
    {
        return Some("python-bind-effect");
    }

    if path.contains("sugar-cli/src/witness_verify.rs") {
        if line.contains("verdict: \"refused\"") {
            return Some("witness-verification-effect");
        }
        if line.contains("oracle refused resolution") {
            return Some("witness-oracle-resolution-effect");
        }
    }
    if path.contains("sugar-cli/src/component_plan.rs")
        && line.contains("component refused workspace")
    {
        return Some("component-plan-decline-effect");
    }
    if path.contains("sugar-cli/src/cmd_compose.rs") && line.contains("RpcError::refused_with_atom")
    {
        return Some("composition-effect-mismatch");
    }
    if path.contains("sugar-walk/src/bin/walk_rpc.rs") && line.contains("\"status\": \"refused\"") {
        return Some("rust-walk-source-effect-status");
    }
    if line.contains("\"status\": \"refused\"") || line.contains("status: \"refused\"") {
        return Some("generic-status-refused-effect");
    }

    if path.contains("sugar-verifier/src/consistency.rs") {
        if line.contains("witness REFUSED by rust package recompute") {
            return Some("unwitnessed-discharge-effect");
        }
        if line.contains("oracle refused resolution") {
            return Some("witness-oracle-resolution-effect");
        }
        if line.contains("ObligationVerdict::Refused") && context.contains("no sound discharger") {
            return Some("no-sound-discharger-effect");
        }
        if line.contains("ObligationVerdict::Refused") && context.contains("provenance KIND") {
            return Some("missing-provenance-kind-effect");
        }
        if line.contains("ObligationVerdict::Refused")
            && context.contains("no sibling to contradict")
        {
            return Some("no-sibling-to-contradict-effect");
        }
        if line.contains("let verdict = ObligationVerdict::Refused")
            && context.contains("count_top_level_constraints")
        {
            return Some("no-sibling-to-contradict-effect");
        }
    }
    if path.contains("sugar-verifier/src/body_discharge.rs") && line.contains("WpError::Refused") {
        return Some("body-reduction-refusal-effect");
    }
    if path.contains("sugar-verifier/src/outlives.rs") && line.contains("DischargeOutcome::Refused")
    {
        return Some("outlives-region-refusal-effect");
    }
    if path.contains("sugar-verifier/src/solvers/subprocess.rs")
        && line.contains("ObligationVerdict::Refused")
    {
        return Some("solver-unsupported-construct-effect");
    }
    if path.contains("sugar-verifier/src/solvers/plan.rs")
        && line.contains("refused: no sound discharger")
    {
        return Some("no-sound-discharger-effect");
    }
    if path.contains("sugar-verifier/src/solvers/batch.rs")
        && line.contains("ObligationVerdict::Refused")
    {
        return Some("solver-batch-refusal-effect");
    }

    if path.contains("libsugar/src/core/path_executor.rs")
        && line.contains("PathExecutionError::Refused")
    {
        return Some("path-composition-refusal-effect");
    }
    if path.contains("libsugar/src/ffi.rs") && line.contains("ComposeRefused") {
        return Some("composition-refusal-effect");
    }
    if path.contains("libsugar/src/wp.rs") {
        if line.contains("enum Refusal") || line.contains("WpError::Refused") {
            return Some("wp-refusal-effect");
        }
    }

    if path.contains("sugar-lift-rust-tests/src") {
        if is_rust_lift_refusal_effect(line) {
            return Some("rust-lift-effect");
        }
        if line.contains("Disposition::Refused") || line.contains("FactoryDisposition::Refused") {
            return Some("rust-lift-terminal-classifier");
        }
        if line.contains("DurationDecision::Refused") {
            return Some("rust-lift-duration-effect");
        }
    }

    if path.contains("sugar-walk/src") && line.contains("panic!") && line.contains("refused") {
        return Some("coverage-panic-wording");
    }

    None
}

fn is_python_unsupported_syntax_constructor(line: &str) -> bool {
    line.contains("raise _UnsupportedSyntax")
        || line.contains("return _UnsupportedSyntax")
        || line.contains("self.refused = _UnsupportedSyntax")
        || line.contains("self._refuse(")
}

fn is_value_pin_refusal(line: &str) -> bool {
    (line.contains("_pin_refusal(") && !line.starts_with("def _pin_refusal"))
        || line.contains("scan.refusals.append(_pin_refusal")
        || line.contains("VALUE_PIN_REFUSAL_KIND =")
        || line.contains("ENUM_PIN_REFUSAL_KIND =")
}

fn is_rust_lift_refusal_effect(line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    lower.contains("refused")
        && (line.contains("reason:")
            || line.contains("format!(")
            || line.contains("return Some(DurationDecision::Refused")
            || line.contains("CellValue::Refused")
            || line.contains("(\"refused\",")
            || line.contains("Outcome::Incomplete")
            || line.contains("refusal_reason"))
}

fn collect_stringly_refusal_consumers(root: &Path) -> Result<Vec<Site>, String> {
    let mut out = Vec::new();
    for source_root in source_roots(root) {
        for path in source_files_under(&source_root)? {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path).map_err(|err| format!("read {}: {err}", rel))?;
            for (idx, line) in source.lines().enumerate() {
                let trimmed = line.trim();
                if classify_consumer(trimmed).is_some() {
                    out.push(Site {
                        ground: "stringly-refusal-consumer".to_string(),
                        path: rel.clone(),
                        line: idx + 1,
                        text: trimmed.to_string(),
                    });
                }
            }
        }
    }
    out.sort();
    Ok(out)
}

fn collect_effect_enum_wildcard_arms(root: &Path) -> Result<Vec<Site>, String> {
    let mut out = Vec::new();
    for source_root in source_roots(root) {
        for path in source_files_under(&source_root)? {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path).map_err(|err| format!("read {}: {err}", rel))?;
            out.extend(collect_effect_enum_wildcard_arms_from_source(&rel, &source));
        }
    }
    out.sort();
    Ok(out)
}

fn collect_effect_enum_wildcard_arms_from_source(path: &str, source: &str) -> Vec<Site> {
    let lines = source.lines().collect::<Vec<_>>();
    let mut out = Vec::new();
    for (idx, line) in lines.iter().enumerate() {
        let trimmed = line.trim();
        if !trimmed.starts_with("_ =>") {
            continue;
        }
        let context = context_window(&lines, idx);
        if let Some(enum_name) = effect_enum_named_in_context(&context) {
            out.push(Site {
                ground: "effect-enum-wildcard-arm".to_string(),
                path: path.to_string(),
                line: idx + 1,
                text: format!("{enum_name}: {trimmed}"),
            });
        }
    }
    out
}

fn effect_enum_named_in_context(context: &str) -> Option<&'static str> {
    for enum_name in [
        "VerifyEffect",
        "WitnessVerificationOutcome",
        // Future effect/result enums join this sweep here as they land.
    ] {
        let variant_prefix = format!("{enum_name}::");
        if context.contains(&variant_prefix) {
            return Some(enum_name);
        }
    }
    None
}

fn classify_consumer(line: &str) -> Option<()> {
    if line.starts_with("//") || line.starts_with("///") || line.starts_with("//!") {
        return None;
    }
    if line.contains("refusal_disposition(")
        || line.contains("reason.contains(")
        || line.contains(".contains(\"refused")
        || line.contains("== Some(\"refused\")")
        || line.contains("== \"refused\"")
        || line.contains("get(\"refused\")")
        || line.contains("get(\"status\")")
        || line.contains("source_count(")
    {
        return Some(());
    }
    None
}

fn expected_as_sites() -> Vec<Site> {
    EXPECTED_STRINGLY_REFUSAL_EMISSIONS
        .iter()
        .map(|site| Site {
            ground: {
                assert_eq!(
                    site.replacement,
                    replacement_for_ground(site.ground),
                    "replacement text for {} must stay in sync with the ground map",
                    site.ground
                );
                site.ground.to_string()
            },
            path: site.path.to_string(),
            line: site.line,
            text: site.needle.to_string(),
        })
        .collect()
}

fn report_vector(sites: &[Site]) -> String {
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for site in sites {
        *counts.entry(&site.ground).or_default() += 1;
    }
    counts
        .into_iter()
        .map(|(ground, count)| format!("{ground}: {count}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn report_sites(sites: &[Site]) -> String {
    sites
        .iter()
        .map(|site| {
            format!(
                "{}\t{}:{}\t{}",
                site.ground, site.path, site.line, site.text
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn expected_literal(sites: &[Site]) -> String {
    let mut out = String::new();
    out.push_str("const EXPECTED_STRINGLY_REFUSAL_EMISSIONS: &[ExpectedSite] = &[\n");
    for site in sites {
        out.push_str(&format!(
            "    ExpectedSite {{ ground: {:?}, path: {:?}, line: {}, needle: {:?}, replacement: {:?} }},\n",
            site.ground,
            site.path,
            site.line,
            site.text,
            replacement_for_ground(&site.ground),
        ));
    }
    out.push_str("];\n");
    out
}

fn replacement_for_ground(ground: &str) -> &'static str {
    match ground {
        "body-reduction-refusal-effect" => "BodyReductionEffect::{WpRefused,PreconditionMissing} carrying callee and WP ground",
        "component-plan-decline-effect" => "ComponentPlanEffect::Declined/Refused with component identity and manifest path",
        "composition-effect-mismatch" => "CompositionEffect::EffectSetMismatch carrying atom CID and parameter index",
        "composition-refusal-effect" => "CompositionEffect variant from CompositionRefusalMemento header kind",
        "coverage-panic-wording" => "coverage ICE/panic with typed frontier owner; do not encode as refused prose",
        "generic-status-refused-effect" => "typed effect variant at the emitting boundary; status string only at final serialization if still required",
        "missing-provenance-kind-effect" => "VerifyEffect::InsufficientEvidence{missing: ProvenanceKind}",
        "no-sibling-to-contradict-effect" => "VerifyEffect::NoSiblingToContradict{obligation}",
        "no-sound-discharger-effect" => "VerifyEffect::NoSoundDischarger{solver}",
        "outlives-region-refusal-effect" => "VerifyEffect::OutlivesNotProvable{longer,shorter}",
        "path-composition-refusal-effect" => "CompositionEffect::MissingRequirement from PathExecutionError",
        "python-bind-effect" => "PythonBindEffect::{MissingBinding,BoundaryBodyShape}",
        "python-kit-effect-dto-status" => "Python EffectDto typed status/effect variant, not status string",
        "python-proofir-refusal-record" => "ProofIREffect node with typed effect_kind and provenance",
        "python-source-oracle-effect" => "SourceOracleEffect::{Absent,Drifted} carrying source memento",
        "python-unsupported-syntax-effect" => "PythonLiftEffect variant for the refused syntax ground",
        "python-value-pin-effect" => "PythonLiftEffect::ValuePinRejected/EnumPinRejected carrying candidate and reason",
        "rust-lift-duration-effect" => "RustLiftEffect::DurationCarrierEmbedding carrying boundary and carrier ground",
        "rust-lift-effect" => "RustLiftEffect variant carrying the source/runtime ground",
        "rust-lift-terminal-classifier" => "RustLiftEffect classifier enum instead of reason-prose whitelist",
        "rust-walk-source-effect-status" => "RustWalk source effect status variant with source ledger ground",
        "solver-batch-refusal-effect" => "SolverEffect::BatchRefused carrying solver and job",
        "solver-unsupported-construct-effect" => "SolverEffect::UnsupportedConstruct{symbol}",
        "unwitnessed-discharge-effect" => "VerifyEffect::UnwitnessedDischarge{witness_cid,ground}",
        "witness-oracle-resolution-effect" => "VerifyEffect::WitnessOracleRefused{resolver,reason}",
        "witness-verification-effect" => "VerifyEffect::WitnessVerificationRefused{check,ground}",
        "wp-refusal-effect" => "WpEffect::{OpaqueLoop,OpaqueCall} surfaced through typed evidence verdict",
        other => panic!("missing replacement for ground {other}"),
    }
}

fn identity_multiset(sites: Vec<Site>) -> BTreeMap<(String, String, String), usize> {
    let mut out = BTreeMap::new();
    for site in sites {
        *out.entry((site.ground, site.path, site.text)).or_default() += 1;
    }
    out
}

#[test]
fn stringly_refusal_emission_frontier_matches_expected_multiset() {
    let root = repo_root();
    let observed =
        collect_stringly_refusal_emissions(&root).expect("collect stringly refusal emissions");
    let expected = expected_as_sites();
    assert_eq!(
        identity_multiset(observed.clone()),
        identity_multiset(expected),
        "R(stringly-refusals) emission frontier changed\n\nObserved vector:\n{}\n\nObserved sites:\n{}\n\nPasteable expected literal:\n{}",
        report_vector(&observed),
        report_sites(&observed),
        expected_literal(&observed),
    );
}

#[test]
fn stringly_refusal_consumer_census_is_reportable() {
    let root = repo_root();
    let consumers =
        collect_stringly_refusal_consumers(&root).expect("collect stringly refusal consumers");
    assert!(
        !consumers.is_empty(),
        "consumer census must keep reporting string/prose consumers until the migration reaches exhaustive effect matches"
    );
}

#[test]
fn effect_enum_wildcard_arm_frontier_is_stable_zero() {
    let root = repo_root();
    let wildcards =
        collect_effect_enum_wildcard_arms(&root).expect("collect effect enum wildcard arms");
    assert!(
        wildcards.is_empty(),
        "R(wildcard-arms-over-effect-enums) must stay 0; typed effect consumers must match each ground explicitly\n\nObserved sites:\n{}",
        report_sites(&wildcards),
    );
}

#[test]
fn planted_stringly_refusal_emission_is_detected() {
    let source = r#"
fn planted() {
    let _ = serde_json::json!({
        "status": "refused",
        "reason": "planted prose ground"
    });
}
"#;
    let sites = collect_stringly_refusal_emissions_from_source(
        "implementations/rust/sugar-cli/src/planted.rs",
        source,
    );
    assert_eq!(
        sites.len(),
        1,
        "planted refused status must be a frontier row"
    );
    assert_eq!(sites[0].ground, "generic-status-refused-effect");
}

#[test]
fn planted_rust_lift_stringly_effect_emission_is_detected() {
    let source = r#"
fn planted(boundary: &str) -> Effect {
    Effect::FormatArgument {
        reason: format!("runtime format argument `{boundary}`, not literal-determined; refused"),
    }
}
"#;
    let sites = collect_stringly_refusal_emissions_from_source(
        "implementations/rust/sugar-lift-rust-tests/src/sugar/planted.rs",
        source,
    );
    assert_eq!(
        sites.len(),
        1,
        "planted Rust lift stringly effect must be a frontier row"
    );
    assert_eq!(sites[0].ground, "rust-lift-effect");
}

#[test]
fn planted_effect_enum_wildcard_arm_is_detected() {
    let source = r#"
fn planted(effect: VerifyEffect) -> &'static str {
    match effect {
        VerifyEffect::MissingProvenanceKind { .. } => "missing",
        _ => "swallowed",
    }
}
"#;
    let sites = collect_effect_enum_wildcard_arms_from_source(
        "implementations/rust/sugar-verifier/src/planted.rs",
        source,
    );
    assert_eq!(
        sites.len(),
        1,
        "planted wildcard over VerifyEffect must be a frontier row"
    );
    assert_eq!(sites[0].ground, "effect-enum-wildcard-arm");
}

#[test]
fn planted_python_stringly_refusal_emission_is_detected() {
    let source = r#"
def planted():
    return {
        "outcome": "refused",
        "reason": "planted python prose ground",
    }
"#;
    let sites = collect_stringly_refusal_emissions_from_source(
        "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/bind_rpc.py",
        source,
    );
    assert_eq!(
        sites.len(),
        1,
        "planted Python refused outcome must be a frontier row"
    );
    assert_eq!(sites[0].ground, "python-bind-effect");
}
