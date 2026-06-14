// SPDX-License-Identifier: Apache-2.0
//
// Rust source to substrate walking.
//
// This crate combines a syn surface lift, Charon LLBC lift, layered marriage,
// effect detection, aliasing, region and pin mementos, and the dropper
// generative-completion path. It emits FunctionContractMemento values,
// proof.ir walk bundles, and algebra terms over the minted rust:rust language
// signature. The crate keeps the IR representation in sugar-ir-types and
// content-addresses emitted artifacts with the shared JCS plus BLAKE3 pipeline.
//
// Remaining growth is incremental signature and memento coverage for more
// Rust syntax, library contracts, and solver-discharged opacity sites.

pub mod aliasing;
pub mod canonical;
pub mod chain;
pub mod charon_runner;
pub mod contract;
pub mod dropper;
pub mod emit;
pub mod envelope;
pub mod lift;
pub mod llbc;
pub mod llbc_calls;
pub mod llbc_closures;
pub mod llbc_lift;
pub mod llbc_loops;
pub mod llbc_try;
pub mod locus;
pub mod loops_and_exceptions;
pub mod marriage;
pub mod ra_daemon_client;
pub mod ra_oracle;
pub mod shadow;
pub mod signature;
pub mod sort_translate;
pub mod type_decl;
pub mod walk;
pub mod wp;

pub use canonical::{
    cid_of_value, formula_to_canonical, jcs_bytes_of_value, serde_to_canonical, term_to_canonical,
};
pub use contract::{
    build_function_contract, build_function_contract_with_file,
    build_function_contract_with_file_and_post_override,
};
pub use dropper::{
    detect_gaps, drop_gap, emit_drop, formula_contains_predicate, predicate_var_arg,
    verify_closure, DropFailure, DropTemplate, EmitResult, Gap, NotNullPredicate, NotRenderable,
    PredicateDescriptor, PredicateRegistry,
};
pub use envelope::{
    mint_args, wrap_function_contract, wrap_function_contract_cached, EnvelopeCache,
    DEV_SIGNER_SEED,
};
pub use lift::{
    collect_explicit_function_return_facts, lift_function_postcondition,
    lift_function_postcondition_with_return_facts,
    lift_function_postcondition_with_return_facts_and_pure_free_guards, lift_function_precondition,
    lift_predicate, pure_free_guard_arg_is_stable, pure_free_guard_expr_effect_roots,
    PureFreeGuardRule,
};
pub use shadow::{
    build_shadow_source, compose_chain, compose_edges, edge_memento_cid, edge_memento_value,
    CalleeContract, ComposedEdge, ShadowArrival, ShadowSlot, ShadowSource,
};
pub use walk::{walk_callsites_to_entry, Arrival, CallsiteWalk};
pub use wp::{
    atomic_ge, atomic_lt, atomic_true, const_int, free_vars_formula, free_vars_term, var, Wp,
};
