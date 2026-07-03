use std::collections::{BTreeMap, BTreeSet};
use std::process::Command;
use std::rc::Rc;
use std::time::{SystemTime, UNIX_EPOCH};

use sugar_ir_symbolic::{num, ConstValue, Sort, Term};
use sugar_lift_rust_tests::sugar::catalog::catalog_claims;
use sugar_lift_rust_tests::{
    emit_value_contract, lift_file, warrant_conjoined_with_vendor_terms, AdapterOutput,
    AssertionFactEmission, AssertionFactKind,
};

const EXPECTED_SEED_CLAIMS: usize = 107;
const EXPECTED_ENROLLMENT_FRONTIER: usize = 98;
const EXPECTED_NOT_VERDICT_BEARING_CLAIMS: usize = 2;
const EXPECTED_TEMPORAL_OPT_OUT_CLAIMS: usize = 4;
const EXPECTED_PENDING_ROUTER_WITNESS_SLOTS: usize = 0;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum PendingResidualClass {
    ReasonedBucket,
    PinnedCatch,
    TemporalCampaign,
}

impl PendingResidualClass {
    const fn as_str(self) -> &'static str {
        match self {
            Self::ReasonedBucket => "reasoned-bucket",
            Self::PinnedCatch => "pinned-catch",
            Self::TemporalCampaign => "temporal-campaign",
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct PendingResidual {
    claim: &'static str,
    class: PendingResidualClass,
    detail: &'static str,
}

const EXPECTED_PENDING_RESIDUALS: &[PendingResidual] = &[
    PendingResidual {
        claim: "addr_of_mut",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unsafe address-of expression; needs pointer-provenance floor before a verdict pair",
    },
    PendingResidual {
        claim: "array_chunks",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: array_chunks literal-iterator standing",
    },
    PendingResidual {
        claim: "array_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch aggregate row: witnesses dispatch through aggregate_decomp/term_literal",
    },
    PendingResidual {
        claim: "assertion_surface_infinity_eq",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family e: float/infinity semantics lie remains SAT",
    },
    PendingResidual {
        claim: "atomic_load",
        class: PendingResidualClass::ReasonedBucket,
        detail: "observable atomic memory read; no stable witness value source yet",
    },
    PendingResidual {
        claim: "await_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "async await runtime handoff; verdict pair needs executor/future witness machinery",
    },
    PendingResidual {
        claim: "bound_path",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch path row: witnesses dispatch through assertion surfaces or term_literal",
    },
    PendingResidual {
        claim: "bound_path_composite",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch bound composite row; pair needs source-owner alignment",
    },
    PendingResidual {
        claim: "call",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family i: generic call EUF semantic lie remains SAT",
    },
    PendingResidual {
        claim: "char_range_collect_string",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: char range collection-to-string",
    },
    PendingResidual {
        claim: "char_range_filter_map_eq",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: char range filter_map equality",
    },
    PendingResidual {
        claim: "char_range_filter_map_eq_assertion_surface",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: assertion-surface char range filter_map equality",
    },
    PendingResidual {
        claim: "closure_iter_advance_body",
        class: PendingResidualClass::ReasonedBucket,
        detail: "closure adaptor runtime iterator advance; needs closure-state witness machinery",
    },
    PendingResidual {
        claim: "closure_mutating_body",
        class: PendingResidualClass::ReasonedBucket,
        detail: "closure adaptor mutates captured state; needs mutable closure-state witness machinery",
    },
    PendingResidual {
        claim: "closure_opaque_accessor",
        class: PendingResidualClass::ReasonedBucket,
        detail: "closure adaptor opaque accessor; no deterministic verdict source",
    },
    PendingResidual {
        claim: "closure_runtime_receiver",
        class: PendingResidualClass::ReasonedBucket,
        detail: "closure adaptor runtime receiver; no literal standing for witness pair",
    },
    PendingResidual {
        claim: "closure_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "closure term identity needs callable/closure witness machinery",
    },
    PendingResidual {
        claim: "closure_tls_accessor",
        class: PendingResidualClass::ReasonedBucket,
        detail: "thread-local closure accessor; runtime TLS state is not verdict-bearing yet",
    },
    PendingResidual {
        claim: "collect",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 collection terminal family: collect materialization",
    },
    PendingResidual {
        claim: "collection_literal",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch collection row: aggregate literal witnesses dispatch elsewhere",
    },
    PendingResidual {
        claim: "compute_float",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family e: compute_float wrapper remains EUF and lying SAT",
    },
    PendingResidual {
        claim: "constraint_assert_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch macro row: assertion witnesses dispatch to assertion-surface macro owners",
    },
    PendingResidual {
        claim: "constraint_bounded_literal_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch macro row: bounded literal assertion witnesses dispatch to assertion surface",
    },
    PendingResidual {
        claim: "constraint_cfg_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "configuration fact surface missing; target-cfg facts need a typed witness source",
    },
    PendingResidual {
        claim: "constraint_float_refinement",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family e: float refinement semantic lie remains SAT",
    },
    PendingResidual {
        claim: "constraint_if_panic",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family g: panic/guard implication semantic lie remains SAT",
    },
    PendingResidual {
        claim: "constraint_infinity_eq",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family e: infinity equality needs the float semantics drain",
    },
    PendingResidual {
        claim: "constraint_literal_iterator_quantifier",
        class: PendingResidualClass::TemporalCampaign,
        detail: "#3415 family j / temporal quantifier cross-chain: finite literal iterator curry facts",
    },
    PendingResidual {
        claim: "constraint_match_scrutinee",
        class: PendingResidualClass::ReasonedBucket,
        detail: "match-scrutinee carrier facts need owner-aligned pattern witness machinery",
    },
    PendingResidual {
        claim: "constraint_relation_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch macro row: relation witnesses dispatch through assertion-surface owners",
    },
    PendingResidual {
        claim: "constraint_runtime_expr",
        class: PendingResidualClass::ReasonedBucket,
        detail: "runtime-expression constraint; needs runtime value witness machinery",
    },
    PendingResidual {
        claim: "control_flow_composite",
        class: PendingResidualClass::ReasonedBucket,
        detail: "control-flow composite effect surface needs statement-position assertion anchoring",
    },
    PendingResidual {
        claim: "cycle_take",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: cycle/take finite standing",
    },
    PendingResidual {
        claim: "dormant_mut_ref",
        class: PendingResidualClass::ReasonedBucket,
        detail: "mutable alias state; needs temporal/mutable-reference witness machinery",
    },
    PendingResidual {
        claim: "flat_map",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: flat_map expansion",
    },
    PendingResidual {
        claim: "flatten",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: flatten expansion",
    },
    PendingResidual {
        claim: "for_each",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter/effect family: for_each closure effects",
    },
    PendingResidual {
        claim: "for_loop_mutation",
        class: PendingResidualClass::ReasonedBucket,
        detail: "loop mutation state; needs guarded temporal statement anchoring",
    },
    PendingResidual {
        claim: "for_replay",
        class: PendingResidualClass::TemporalCampaign,
        detail: "family-j temporal quantifier cross-chain: replayed loop members",
    },
    PendingResidual {
        claim: "forall_loop",
        class: PendingResidualClass::TemporalCampaign,
        detail: "family-j temporal quantifier cross-chain: forall loop facts",
    },
    PendingResidual {
        claim: "format_args_estimated_capacity",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unstable-feature bucket: fmt_internals capacity is not stable Rust witness ground",
    },
    PendingResidual {
        claim: "function_map",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: named function map composition",
    },
    PendingResidual {
        claim: "function_map_term",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: named function map as term",
    },
    PendingResidual {
        claim: "future_join",
        class: PendingResidualClass::ReasonedBucket,
        detail: "async future join runtime handoff; no stable verdict witness yet",
    },
    PendingResidual {
        claim: "identity_map",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: identity map standing",
    },
    PendingResidual {
        claim: "intersperse",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: intersperse sequence expansion",
    },
    PendingResidual {
        claim: "intersperse_collect_string",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unstable-feature bucket: iter_intersperse collection string witness blocked",
    },
    PendingResidual {
        claim: "intersperse_concat",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unstable-feature bucket: iter_intersperse concat witness blocked",
    },
    PendingResidual {
        claim: "iter_next",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator state family: next() consumption",
    },
    PendingResidual {
        claim: "iter_terminal",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator terminal family",
    },
    PendingResidual {
        claim: "iterator",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: base iterator standing",
    },
    PendingResidual {
        claim: "kmerge",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: k-way merge standing",
    },
    PendingResidual {
        claim: "literal_ip_addr",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family c: literal IP address value relation lie remains SAT",
    },
    PendingResidual {
        claim: "map_term",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: map term projection",
    },
    PendingResidual {
        claim: "match_scrutinee",
        class: PendingResidualClass::ReasonedBucket,
        detail: "match scrutinee verdict needs owner-aligned pattern witness machinery",
    },
    PendingResidual {
        claim: "match_scrutinee_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "match scrutinee term needs owner-aligned pattern witness machinery",
    },
    PendingResidual {
        claim: "method",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family i: generic method EUF semantic lie remains SAT",
    },
    PendingResidual {
        claim: "monadic_composite",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S6 Option-Result family: monadic composite routing",
    },
    PendingResidual {
        claim: "panic_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "effect-router surface; needs statement-position handler witness before verdict pair",
    },
    PendingResidual {
        claim: "path",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch fallback path row; witnesses dispatch to const/bound/term owners",
    },
    PendingResidual {
        claim: "peekable",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator state family: peekable adaptor",
    },
    PendingResidual {
        claim: "peekable_runtime_assertion_surface",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator state family: peekable assertion surface",
    },
    PendingResidual {
        claim: "ptr_eq_term",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family h: pointer identity semantic lie remains SAT",
    },
    PendingResidual {
        claim: "ptr_metadata",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unstable pointer metadata facts need typed pointer-provenance machinery",
    },
    PendingResidual {
        claim: "range_bounds_contains",
        class: PendingResidualClass::TemporalCampaign,
        detail: "family-j temporal quantifier cross-chain: RangeBounds contains facts",
    },
    PendingResidual {
        claim: "range_construct",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch range row: probes dispatch to range_term/struct_term/aggregate surfaces",
    },
    PendingResidual {
        claim: "raw_addr_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "raw address term needs pointer-provenance facts before verdict pair",
    },
    PendingResidual {
        claim: "raw_pointer_arithmetic",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unsafe pointer arithmetic; no stable proof relation yet",
    },
    PendingResidual {
        claim: "reference_sequence",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator/reference sequence standing",
    },
    PendingResidual {
        claim: "repeat_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch aggregate row: repeat witnesses dispatch through aggregate_decomp/term_literal",
    },
    PendingResidual {
        claim: "result_inspect",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S6 Option-Result family: inspect on Result",
    },
    PendingResidual {
        claim: "result_transpose_collect",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family f: Result transpose/collect collection-shape lie remains SAT",
    },
    PendingResidual {
        claim: "rev",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: rev ordering",
    },
    PendingResidual {
        claim: "runtime_iterator_source",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator standing: runtime source remains effectful",
    },
    PendingResidual {
        claim: "scan",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: scan stateful composition",
    },
    PendingResidual {
        claim: "slice_chunk_window",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: slice chunks/windows",
    },
    PendingResidual {
        claim: "slice_index",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unstable-feature bucket: slice_index_methods is not stable Rust witness ground",
    },
    PendingResidual {
        claim: "source_location",
        class: PendingResidualClass::ReasonedBucket,
        detail: "source-location value is compile-context metadata, not a semantic witness yet",
    },
    PendingResidual {
        claim: "statement_async_future",
        class: PendingResidualClass::ReasonedBucket,
        detail: "async statement/future handoff; no verdict-bearing runtime witness",
    },
    PendingResidual {
        claim: "statement_control_flow",
        class: PendingResidualClass::ReasonedBucket,
        detail: "statement control-flow effect needs statement-position assertion anchoring",
    },
    PendingResidual {
        claim: "statement_future_handoff",
        class: PendingResidualClass::ReasonedBucket,
        detail: "future handoff statement effect; no deterministic verdict source",
    },
    PendingResidual {
        claim: "statement_future_handoff_composite",
        class: PendingResidualClass::ReasonedBucket,
        detail: "future handoff composite; no deterministic verdict source",
    },
    PendingResidual {
        claim: "statement_loop_advance",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5/S6 iterator-state family: statement loop advance",
    },
    PendingResidual {
        claim: "statement_nested_assertion",
        class: PendingResidualClass::ReasonedBucket,
        detail: "nested assertion statement needs statement-position assertion anchoring",
    },
    PendingResidual {
        claim: "statement_reflection",
        class: PendingResidualClass::ReasonedBucket,
        detail: "reflection statement; no stable semantic witness relation yet",
    },
    PendingResidual {
        claim: "statement_runtime_expr",
        class: PendingResidualClass::ReasonedBucket,
        detail: "runtime expression statement; no stable value source in witness harness",
    },
    PendingResidual {
        claim: "statement_unsafe_memory",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unsafe-memory statement effect; no stable proof relation yet",
    },
    PendingResidual {
        claim: "step_by",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S5 adapter family: step_by standing",
    },
    PendingResidual {
        claim: "str_table_select",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family k: bv/table-select/string conversion lie remains SAT",
    },
    PendingResidual {
        claim: "struct_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch aggregate row: struct witnesses dispatch through aggregate_decomp/term_literal",
    },
    PendingResidual {
        claim: "transparent_composite",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch transparent composite row; witnesses dispatch to transparent_term",
    },
    PendingResidual {
        claim: "try_from_fn",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S6 Option-Result family: try_from_fn fallible iteration",
    },
    PendingResidual {
        claim: "try_map",
        class: PendingResidualClass::TemporalCampaign,
        detail: "S6 Option-Result family: try_map fallible adaptor",
    },
    PendingResidual {
        claim: "tuple_term",
        class: PendingResidualClass::ReasonedBucket,
        detail: "owner-mismatch aggregate row: tuple witnesses dispatch through tuple_decomp/term_literal",
    },
    PendingResidual {
        claim: "unsafe_memory",
        class: PendingResidualClass::ReasonedBucket,
        detail: "unsafe-memory expression effect; no stable proof relation yet",
    },
    PendingResidual {
        claim: "vec_literal",
        class: PendingResidualClass::ReasonedBucket,
        detail: "production-panic bucket: vector literal term production still panics/unsupported",
    },
    PendingResidual {
        claim: "vec_macro",
        class: PendingResidualClass::PinnedCatch,
        detail: "#3415 family b/f: direct vec equality lie fixed via aggregate decomposition (#3430); nested/non-direct vec shapes still SAT; enrollment blocked on owner-correct Pair shape",
    },
    PendingResidual {
        claim: "write_macro",
        class: PendingResidualClass::ReasonedBucket,
        detail: "formatting/write side effect; no deterministic verdict-bearing output witness",
    },
];

#[test]
fn s9_batch5_residual_pending_map_covers_every_row() {
    let actual = catalog_claims()
        .into_iter()
        .filter(|claim| claim.witnesses.is_pending())
        .map(|claim| claim.name)
        .collect::<BTreeSet<_>>();
    let mut expected = BTreeSet::new();
    let mut counts = BTreeMap::<&'static str, usize>::new();
    for row in EXPECTED_PENDING_RESIDUALS {
        assert!(
            !row.detail.trim().is_empty(),
            "residual row `{}` must name the blocker or owner",
            row.claim
        );
        assert!(
            expected.insert(row.claim),
            "duplicate residual row `{}`",
            row.claim
        );
        *counts.entry(row.class.as_str()).or_default() += 1;
    }
    let missing = actual.difference(&expected).copied().collect::<Vec<_>>();
    let stale = expected.difference(&actual).copied().collect::<Vec<_>>();
    println!(
        "R(rust-witness-residual-map)={} class_counts={:?}",
        EXPECTED_PENDING_RESIDUALS.len(),
        counts
    );
    assert!(
        missing.is_empty() && stale.is_empty(),
        "S9 batch 5 residual map must classify every Pending claim exactly once; missing={missing:?}; stale={stale:?}"
    );
    assert_eq!(actual.len(), EXPECTED_ENROLLMENT_FRONTIER);
}

#[derive(Clone, Copy)]
struct WitnessPair {
    claim: &'static str,
    truthful: &'static str,
    lying: &'static str,
}

#[derive(Clone, Copy)]
struct PendingRouterWitnessSlot {
    router: &'static str,
    owner_slice: &'static str,
    truthful_slot: &'static str,
    lying_slot: &'static str,
}

fn pending_router_witness_slots() -> Vec<PendingRouterWitnessSlot> {
    Vec::new()
}

fn seed_witnesses() -> Vec<WitnessPair> {
    catalog_claims()
        .into_iter()
        .filter_map(|claim| match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::Pair { truthful, lying } => {
                Some(WitnessPair {
                    claim: claim.name,
                    truthful,
                    lying,
                })
            }
            _ => None,
        })
        .collect()
}
fn parse(src: &str) -> syn::File {
    syn::parse_file(src).expect("witness source parses")
}

fn warranted_facts(out: &AdapterOutput) -> Vec<&AssertionFactEmission> {
    out.assertion_facts
        .iter()
        .filter(|fact| fact.kind == AssertionFactKind::Warranted && fact.claim_count > 0)
        .collect()
}

fn single_warranted_decl(out: &AdapterOutput) -> &sugar_ir_symbolic::ContractDecl {
    let facts = warranted_facts(out);
    let decls: Vec<_> = out
        .decls
        .iter()
        .filter(|decl| {
            facts
                .iter()
                .any(|fact| fact.contract_name.as_str() == decl.name)
        })
        .collect();
    assert_eq!(
        decls.len(),
        1,
        "expected exactly one claim-bearing warranted decl; facts={:?}; decls={:?}; skips={:?}",
        out.assertion_facts,
        out.decls,
        out.skip_reasons
    );
    decls[0]
}

fn inv_json(decl: &sugar_ir_symbolic::ContractDecl) -> serde_json::Value {
    let doc = sugar_ir_symbolic::serialize::marshal_declarations(std::slice::from_ref(decl));
    let parsed: serde_json::Value = serde_json::from_str(&doc).unwrap();
    parsed[0]["inv"].clone()
}

fn resolve_z3_from(z3_env: Option<&str>, path_env: &str) -> Result<String, String> {
    if let Some(path) = z3_env.filter(|value| !value.trim().is_empty()) {
        if Command::new(path)
            .arg("--version")
            .output()
            .map(|out| out.status.success())
            .unwrap_or(false)
        {
            return Ok(path.to_string());
        }
        return Err(format!("Z3 points at a non-executable solver: {path}"));
    }
    for dir in path_env.split(':').filter(|dir| !dir.is_empty()) {
        let candidate = std::path::Path::new(dir).join("z3");
        if candidate.is_file()
            && Command::new(&candidate)
                .arg("--version")
                .output()
                .map(|out| out.status.success())
                .unwrap_or(false)
        {
            return Ok(candidate.display().to_string());
        }
    }
    Err("sugar witness triple harness requires z3 on PATH or Z3=/path/to/z3".to_string())
}

fn z3_path_or_panic() -> String {
    let z3_env = std::env::var("Z3").ok();
    let path_env = std::env::var("PATH").unwrap_or_default();
    resolve_z3_from(z3_env.as_deref(), &path_env).unwrap_or_else(|err| panic!("{err}"))
}

fn compile_asserted_json_to_parts(
    formula: &serde_json::Value,
) -> Result<sugar_ir_compiler::CompiledFormula, sugar_ir_compiler::CompileError> {
    match sugar_ir_compiler::CompilerInput::decode_json(formula.clone())? {
        sugar_ir_compiler::CompilerInput::Formula(formula) => {
            sugar_ir_compiler_smt_lib::compile_asserted_formula_to_parts(formula.formula())
        }
        _ => Err(sugar_ir_compiler::CompileError::MalformedIr(
            "asserted SMT-LIB compile expects a formula input".to_string(),
        )),
    }
}

fn z3_verdict(inv: &serde_json::Value, label: &str, z3: &str) -> bool {
    let parts = compile_asserted_json_to_parts(inv).expect("witness inv must compile to SMT-LIB");
    let script = format!("{}{}\n(check-sat)\n", parts.preamble, parts.body);
    let path = std::env::temp_dir().join(format!("sugar_witness_triple_{label}.smt2"));
    std::fs::write(&path, &script).expect("write witness smt2");
    let out = Command::new(z3).arg(&path).output().expect("run z3");
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        !stdout.contains("unknown constant") && !stdout.to_lowercase().contains("error"),
        "witness relation must be well-sorted:\n{stdout}\n--- {script}"
    );
    stdout.contains("sat") && !stdout.contains("unsat")
}

fn selected_claims(out: &AdapterOutput) -> BTreeSet<&'static str> {
    out.factory_audits
        .iter()
        .filter_map(|audit| audit.selected)
        .collect()
}

fn assert_witness_dispatches_to_owner(claim: &str, out: &AdapterOutput) -> Result<(), String> {
    let selected = selected_claims(out);
    if selected.contains(claim) {
        Ok(())
    } else {
        Err(format!(
            "witness expected claim `{claim}` but selected {:?}",
            selected
        ))
    }
}

#[test]
fn z3_absence_is_a_loud_harness_error() {
    let err = resolve_z3_from(None, "").expect_err("empty PATH must not silently skip z3");
    assert!(
        err.contains("requires z3"),
        "z3 absence must be a loud harness error, got {err:?}"
    );
}

#[test]
fn phase2_question_mark_ok_path_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let truthful = r#"
        #[test]
        fn t_question_mark_ok_good() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let lying = r#"
        #[test]
        fn t_question_mark_ok_bad() -> Result<(), i32> {
            let x = Ok::<i32, i32>(7)?;
            assert_eq!(x, 8);
            Ok(())
        }
    "#;
    let mut verdict_receipt = Vec::new();

    for (label, src, expected_sat) in [
        ("phase2_question_mark_ok_good", truthful, true),
        ("phase2_question_mark_ok_bad", lying, false),
    ] {
        let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
        let decl = single_warranted_decl(&out);
        let got_sat = z3_verdict(&inv_json(decl), label, &z3);
        verdict_receipt.push(format!("{label}={}", if got_sat { "SAT" } else { "UNSAT" }));
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; skips={:?}",
            out.skip_reasons
        );
    }
    println!(
        "phase2 TrySugar acceptance via lift_file -> inv_json -> z3_verdict: {}",
        verdict_receipt.join(", ")
    );
}

#[test]
fn phase2_question_mark_err_path_remains_uncaught_boundary() {
    let src = r#"
        #[test]
        fn t_question_mark_err_uncaught() -> Result<(), i32> {
            let x = Err::<i32, i32>(9)?;
            assert_eq!(x, 7);
            Ok(())
        }
    "#;
    let out = lift_file(
        &parse(src),
        "sugar-witness/phase2_question_mark_err_uncaught.rs",
    );
    assert!(
        warranted_facts(&out).is_empty(),
        "uncaught Err(_)? must not fabricate a warranted assertion; facts={:?}",
        out.assertion_facts
    );
    let rendered = format!("{:?} {:?}", out.assertion_facts, out.skip_reasons);
    assert!(
        rendered.contains("result error raise effect") || rendered.contains("ResultErr"),
        "uncaught Err(_)? should surface the typed ResultErr boundary, got {rendered}"
    );
}

#[test]
fn phase2_early_return_branch_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn pick(flag: bool) -> i32 {
            if flag {
                return 5;
            }
            7
        }
    "#,
    )
    .expect("early-return source parses");
    let decl = emit_value_contract("pick", &function.block)
        .expect("early-return source contract emits through the route spine");
    let flag_true = bool_term(true);

    for (label, expected_out, expected_sat) in [
        ("phase2_early_return_good", 5, true),
        ("phase2_early_return_bad", 6, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_true))],
            num(expected_out),
        );
        let got_sat = z3_verdict(&inv_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
}

fn return_sugar_value_contract_verdict(
    src: &str,
    expected_out: i128,
    label: &str,
    z3: &str,
) -> bool {
    let parsed = parse(src);
    let function = parsed
        .items
        .iter()
        .find_map(|item| match item {
            syn::Item::Fn(function) if function.sig.ident == "pick" => Some(function),
            _ => None,
        })
        .expect("return_sugar witness must define pick");
    let decl = emit_value_contract("pick", &function.block)
        .expect("return_sugar witness must emit through the value-contract route spine");
    let conjoined =
        warrant_conjoined_with_vendor_terms(&decl, &[("flag", bool_term(true))], num(expected_out));
    z3_verdict(&inv_json(&conjoined), label, z3)
}

fn run_rust_test_source(claim: &str, kind: &str, src: &str) -> bool {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time after epoch")
        .as_nanos();
    let safe_claim = claim.replace(|c: char| !c.is_ascii_alphanumeric(), "_");
    let stem = format!(
        "sugar_witness_ground_truth_{}_{}_{}_{}",
        std::process::id(),
        nonce,
        safe_claim,
        kind
    );
    let source_path = std::env::temp_dir().join(format!("{stem}.rs"));
    let binary_path = std::env::temp_dir().join(stem);
    std::fs::write(&source_path, src).expect("write ground-truth Rust source");
    let compile = Command::new("rustc")
        .args(["--edition=2021", "--test"])
        .arg(&source_path)
        .arg("-o")
        .arg(&binary_path)
        .output()
        .expect("run rustc for ground-truth witness");
    assert!(
        compile.status.success(),
        "ground-truth Rust witness {claim}/{kind} must compile:\nstdout={}\nstderr={}",
        String::from_utf8_lossy(&compile.stdout),
        String::from_utf8_lossy(&compile.stderr)
    );
    let run = Command::new(&binary_path)
        .output()
        .expect("run ground-truth Rust test binary");
    let _ = std::fs::remove_file(&source_path);
    let _ = std::fs::remove_file(&binary_path);
    run.status.success()
}

#[test]
fn phase2_guarded_panic_branch_has_solver_bad_twin() {
    let z3 = z3_path_or_panic();
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn guarded(flag: bool) -> i32 {
            if flag {
                panic!()
            }
            7
        }
    "#,
    )
    .expect("guarded panic source parses");
    let decl = emit_value_contract("guarded", &function.block)
        .expect("guarded panic source contract emits through the route spine");
    let flag_false = bool_term(false);

    for (label, expected_out, expected_sat) in [
        ("phase2_guarded_panic_good", 7, true),
        ("phase2_guarded_panic_bad", 8, false),
    ] {
        let conjoined = warrant_conjoined_with_vendor_terms(
            &decl,
            &[("flag", Rc::clone(&flag_false))],
            num(expected_out),
        );
        let got_sat = z3_verdict(&inv_json(&conjoined), label, &z3);
        assert_eq!(
            got_sat, expected_sat,
            "{label}: expected SAT={expected_sat} got SAT={got_sat}; decl={conjoined:?}"
        );
    }
}

#[test]
fn phase2_uncaught_panic_remains_residual_refusal() {
    let function: syn::ItemFn = syn::parse_str(
        r#"
        fn explode() -> i32 {
            panic!()
        }
    "#,
    )
    .expect("uncaught panic source parses");
    let decl = emit_value_contract("explode", &function.block);
    assert!(
        decl.is_none(),
        "a bare panic has no normal return formula to fabricate: {decl:?}"
    );
}

#[test]
fn phase2_noop_drop_does_not_perturb_assertion_emission() {
    let without_drop = lift_file(
        &parse(
            r#"
            #[test]
            fn t_noop_drop_without() {
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_without.rs",
    );
    let with_drop = lift_file(
        &parse(
            r#"
            struct NoopDrop;

            impl Drop for NoopDrop {
                fn drop(&mut self) {}
            }

            #[test]
            fn t_noop_drop_with() {
                let _guard = NoopDrop;
                assert_eq!(1 + 1, 2);
            }
        "#,
        ),
        "sugar-witness/phase2_noop_drop_with.rs",
    );

    assert_eq!(
        inv_json(single_warranted_decl(&with_drop)),
        inv_json(single_warranted_decl(&without_drop)),
        "a no-op Drop must not perturb the emitted assertion invariant; with_drop facts={:?}; skips={:?}",
        with_drop.assertion_facts,
        with_drop.skip_reasons
    );
}

fn bool_term(value: bool) -> Rc<Term> {
    Rc::new(Term::Const {
        value: ConstValue::Bool(value),
        sort: Sort::bool(),
    })
}

#[test]
fn witness_catalog_seed_frontier_is_pinned() {
    let catalog = catalog_claims();
    let seeded: BTreeSet<_> = seed_witnesses()
        .into_iter()
        .map(|pair| pair.claim)
        .collect();
    let claim_names: BTreeSet<_> = catalog.iter().map(|claim| claim.name).collect();
    for seed in &seeded {
        assert!(
            claim_names.contains(seed),
            "seed witness names non-catalog claim `{seed}`"
        );
    }
    let pending: Vec<_> = catalog
        .iter()
        .filter(|claim| claim.witnesses.is_pending())
        .collect();
    let not_verdict_bearing = catalog
        .iter()
        .filter(|claim| {
            matches!(
                claim.witnesses,
                sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing { .. }
            )
        })
        .count();
    let temporal_opt_outs = catalog
        .iter()
        .filter(|claim| {
            matches!(
                claim.witnesses,
                sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut { .. }
            )
        })
        .count();
    for claim in catalog.iter().filter(|claim| {
        matches!(
            claim.witnesses,
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing { .. }
        )
    }) {
        match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::NotVerdictBearing {
                floor,
                reason,
            } => {
                assert!(
                    !floor.trim().is_empty(),
                    "NotVerdictBearing claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    !reason.trim().is_empty(),
                    "NotVerdictBearing claim `{}` must justify the opt-out",
                    claim.name
                );
            }
            _ => unreachable!(),
        }
    }
    for claim in catalog.iter().filter(|claim| {
        matches!(
            claim.witnesses,
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut { .. }
        )
    }) {
        match claim.witnesses {
            sugar_lift_rust_tests::sugar::claim::SugarWitnesses::TemporalOptOut {
                floor,
                reason,
                retirement,
            } => {
                assert!(
                    !floor.trim().is_empty(),
                    "TemporalOptOut claim `{}` must name its floor",
                    claim.name
                );
                assert!(
                    !reason.trim().is_empty(),
                    "TemporalOptOut claim `{}` must justify the opt-out",
                    claim.name
                );
                assert!(
                    !retirement.trim().is_empty(),
                    "TemporalOptOut claim `{}` must name its retirement condition",
                    claim.name
                );
            }
            _ => unreachable!(),
        }
    }
    println!(
        "R(witness-seed-claims)={} R(rust-witness-enrollment-frontier)={} R(rust-witness-not-verdict-bearing)={} R(rust-temporal-opt-outs)={}",
        seeded.len(),
        pending.len(),
        not_verdict_bearing,
        temporal_opt_outs
    );
    assert_eq!(seeded.len(), EXPECTED_SEED_CLAIMS);
    assert_eq!(pending.len(), EXPECTED_ENROLLMENT_FRONTIER);
    assert_eq!(not_verdict_bearing, EXPECTED_NOT_VERDICT_BEARING_CLAIMS);
    assert_eq!(temporal_opt_outs, EXPECTED_TEMPORAL_OPT_OUT_CLAIMS);
    assert_eq!(
        seeded.len() + pending.len() + not_verdict_bearing + temporal_opt_outs,
        catalog.len(),
        "every catalog claim must be exactly Pair, Pending, NotVerdictBearing, or TemporalOptOut"
    );
}

#[test]
fn phase2_router_witness_bad_twin_registry_is_armed_at_zero() {
    let slots = pending_router_witness_slots();
    let names = slots
        .iter()
        .map(|slot| slot.router)
        .collect::<BTreeSet<_>>();
    assert_eq!(
        names.len(),
        slots.len(),
        "router witness slots must be uniquely named"
    );
    for slot in &slots {
        assert!(
            !slot.truthful_slot.trim().is_empty() && !slot.lying_slot.trim().is_empty(),
            "router {} must reserve both truthful and lying bad-twin slots",
            slot.router
        );
    }
    println!(
        "R(routers-without-witness-bad-twin)={} pending={:?}",
        slots.len(),
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
    assert!(
        slots.is_empty(),
        "Phase 2 router witness registry is armed at stable zero; new pending slot(s) must land with truthful+lying bad twins: {:?}",
        slots
            .iter()
            .map(|slot| format!("{}:{}", slot.owner_slice, slot.router))
            .collect::<Vec<_>>()
    );
    assert_eq!(slots.len(), EXPECTED_PENDING_ROUTER_WITNESS_SLOTS);
}

#[test]
fn seed_witnesses_satisfy_the_triple() {
    let z3 = z3_path_or_panic();
    let mut failures = Vec::new();
    let mut owner_mismatches = Vec::new();
    for witness in seed_witnesses() {
        if witness.claim == "return_sugar" {
            for (kind, src, expected_out, expected_sat) in [
                ("truthful", witness.truthful, 5, true),
                ("lying", witness.lying, 6, false),
            ] {
                let label = format!("{}_{}", witness.claim, kind);
                let got_sat = return_sugar_value_contract_verdict(src, expected_out, &label, &z3);
                if got_sat != expected_sat {
                    failures.push(format!(
                        "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                    ));
                }
            }
            continue;
        }
        for (kind, src, expected_sat) in [
            ("truthful", witness.truthful, true),
            ("lying", witness.lying, false),
        ] {
            let label = format!("{}_{}", witness.claim, kind);
            let out = lift_file(&parse(src), &format!("sugar-witness/{label}.rs"));
            if let Err(err) = assert_witness_dispatches_to_owner(witness.claim, &out) {
                owner_mismatches.push(format!("{label}: {err}"));
                continue;
            }
            let decl = single_warranted_decl(&out);
            let got_sat = z3_verdict(&inv_json(decl), &label, &z3);
            if got_sat != expected_sat {
                failures.push(format!(
                    "{label}: expected SAT={expected_sat} got SAT={got_sat}"
                ));
            }
        }
    }
    println!(
        "R(witness-triples-failing)={} R(witnesses-not-dispatching-to-owner)={}",
        failures.len(),
        owner_mismatches.len()
    );
    assert!(owner_mismatches.is_empty(), "{owner_mismatches:#?}");
    assert!(failures.is_empty(), "{failures:#?}");
}

#[test]
fn corrected_s8_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    for claim in ["const_item", "fold", "map", "return_sugar"] {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch1_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "term_literal",
        "const_block",
        "const",
        "binop",
        "bv_binop",
        "constraint_bool_bitwise",
        "unary",
        "wrapping_neg",
        "int_pow",
        "int_sqrt",
        "cast_term",
        "option_predicate",
        "result_predicate",
        "option_unwrap",
        "is_empty",
        "is_sorted",
        "str_method",
        "to_string",
        "constraint_string_predicate",
        "constraint_char_literal_method",
        "slice_accessor",
        "slice_search",
        "range_accessor",
        "range_term",
        "sizeof",
        "offset_of",
        "duration_value",
        "into",
        "nonzero_new",
        "nonzero_assoc_const",
        "nonzero_get",
        "float_literal_method",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch2_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "concat_macro",
        "assertion_surface_relation_macro",
        "assertion_surface_bounded_literal_macro",
        "macro_assertion_surface",
        "assertion_surface_assert_macro",
        "constraint_bool_expr",
        "constraint_tuple_decomp",
        "string_add",
        "index",
        "maybe_uninit_new",
        "maybe_uninit_zeroed",
        "mem_zeroed",
        "try_from",
        "constraint_literal_ip_addr_property",
        "dyn_any",
        "cstr",
        "array_try_from",
        "literal_tuple_producer",
        "array_repeat",
        "field_term",
        "format_macro",
        "block_term",
        "partition_point",
        "option_adaptor",
        "transparent_term",
        "value_if",
        "cell_refcell",
        "literal",
        "const_composite",
        "primitive_int_tuple_producer",
        "slice_search_assertion_surface",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch3_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "cfg_select_assertion_surface",
        "integer_decode_tuple_producer",
        "memchr",
        "macro_term",
        "constraint_matches_macro",
        "control_flow_term",
        "conditional",
        "match_node",
        "constraint_closed_match",
        "constraint_regex_match",
        "constraint_no_panic_call",
        "size_hint_tuple_producer",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s9_batch4_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "bound_constraint",
        "bound_path_tuple_producer",
        "reference_term",
        "literal_slice",
        "loop_break_term",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn s5_adapter_pairs_match_real_rust_semantics() {
    let witnesses = seed_witnesses();
    let claims = [
        "filter",
        "filter_map",
        "take",
        "take_while",
        "skip",
        "skip_while",
        "chain",
        "zip",
        "enumerate",
        "inspect",
    ];
    for claim in claims {
        let witness = witnesses
            .iter()
            .find(|witness| witness.claim == claim)
            .unwrap_or_else(|| panic!("{claim} must be enrolled as a seed witness"));
        let truthful = run_rust_test_source(claim, "truthful", witness.truthful);
        let lying = run_rust_test_source(claim, "lying", witness.lying);
        println!(
            "ground-truth Rust semantics: {claim}/truthful={} {claim}/lying={}",
            if truthful { "PASS" } else { "FAIL" },
            if lying { "PASS" } else { "FAIL" }
        );
        assert!(truthful, "{claim} truthful witness must pass as real Rust");
        assert!(!lying, "{claim} lying witness must fail as real Rust");
    }
}

#[test]
fn assertion_one_names_owner_mismatch() {
    let witness = seed_witnesses()
        .into_iter()
        .find(|pair| pair.claim == "from_bool")
        .expect("from_bool seed exists");
    let out = lift_file(
        &parse(witness.truthful),
        "sugar-witness/misattributed_from_bool.rs",
    );
    let err = assert_witness_dispatches_to_owner("duration_accessor", &out)
        .expect_err("wrong owner must be named as an assertion-1 mismatch");
    assert!(
        err.contains("duration_accessor") && err.contains("from_bool"),
        "mismatch should name expected and selected claims, got {err}"
    );
}
