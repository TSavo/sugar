// SPDX-License-Identifier: Apache-2.0
//
// Silent-drop frontier auditor (#2997).
//
// This is an IDD instrument, not a drain. It scans the Rust lift kit source for
// silent catch-all/default shapes that can hide unhandled syn/LLBC surface:
// wildcard match arms that do nothing or return None, and Option/Result
// conversion/default calls that erase failure. Each offender remains visible
// until a later drain either makes it loud/total or sanctions the specific site.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use syn::spanned::Spanned;
use syn::visit::Visit;

const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[
    (
        "ok",
        "implementations/rust/sugar-lift-contracts/src/bin/contracts_rpc.rs",
        "enumerate_rs_files",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-lift/src/lib.rs",
        "enumerate_rs_files",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-lift/src/lib.rs",
        "to_relative_posix",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/bin/hover_probe.rs",
        "main",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/dropper/emit.rs",
        "emit_drop",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/dropper/emit.rs",
        "emit_drop",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "arm_scalar_to_ir_term",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "arm_scalar_to_ir_term",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "constant_to_ir_term",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "constant_to_ir_term",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "parse_pos_key",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "parse_pos_key",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "ready_timeout_ms",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "ready_timeout_ms",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "ensure_open",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "read_framed_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "read_framed_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "read_framed_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "read_framed_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "resolve_crate",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "start",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "write_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "write_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "write_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "write_message",
        "ok",
    ),
    (
        "ok",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "extract_term_source",
        "ok",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift-contracts/src/bin/contracts_rpc.rs",
        "dispatch",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift-contracts/src/bin/contracts_rpc.rs",
        "dispatch",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "collect_doc_attrs",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "is_bare_generic",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "sig_non_zero_param_produces_refined_domain_evidence",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "contract_decl_to_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "formula_pair",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "lift_path",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "lift_path",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "lift_path",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "run_rpc_mode",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "run_rpc_mode",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "run_rpc_mode",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-lift/src/lib.rs",
        "run_rpc_mode",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/aliasing.rs",
        "has_unsafecell_transitive",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/aliasing.rs",
        "is_mut_ref_charon_ty",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/aliasing.rs",
        "is_shared_ref_charon_ty",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/charon_runner.rs",
        "invoke_charon_on_rs_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/charon_runner.rs",
        "invoke_charon_on_rs_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/charon_runner.rs",
        "write_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/contract.rs",
        "collect_panic_loci",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/dropper/gap.rs",
        "detect_gaps",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/emit.rs",
        "concept_sort_from_type",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/emit.rs",
        "literal_arg_term",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/emit.rs",
        "with_ssa_rebinding",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/envelope.rs",
        "mint_args",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc.rs",
        "is_unsafe",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_calls.rs",
        "lift_llbc_crate",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_closures.rs",
        "collect_in_stmt",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_closures.rs",
        "find_closure_body_cid",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "lift_llbc_function_with_registry",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "lift_llbc_function_with_registry",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "overflow_op_tag",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_loops.rs",
        "locus_of_block",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_loops.rs",
        "locus_of_block",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_loops.rs",
        "locus_of_block",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/llbc_try.rs",
        "callee_is_try_branch",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "ready_timeout_ms",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "request_readiness",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "request_readiness",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "resolve_receiver_crates",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "resolve_receiver_crates",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "resolve_receiver_crates",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_daemon_client.rs",
        "resolve_receiver_crates",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "crate_from_uri",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "definition_result",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "locate_rust_analyzer",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "respond_if_server_request",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "rustup_toolchain_env_for",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "type_stem_from_uri",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "type_stem_from_uri",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/sort_translate.rs",
        "charon_inner_to_sort_name",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/sort_translate.rs",
        "charon_inner_to_sort_name",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "expr_to_template",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "line_column_to_byte_offset_with_starts",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "resolve_source_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "resolve_source_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "resolve_source_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "resolve_source_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "resolve_source_memento",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "stmt_to_template",
        "unwrap_or",
    ),
    (
        "unwrap_or",
        "implementations/rust/sugar-walk/src/walk.rs",
        "walk_expr_for_callsites",
        "unwrap_or",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-lift/src/lib.rs",
        "new",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-lift/src/lib.rs",
        "proof_member_headers",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-lift/src/lib.rs",
        "run_rpc_mode",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/contract.rs",
        "scan_macro_for_effects",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/envelope.rs",
        "mint_args",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/llbc_calls.rs",
        "extract_call_target",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "block_statements",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "resolve_batch",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "start",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "wait_until_quiescent",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/shadow.rs",
        "build_shadow_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/shadow.rs",
        "build_shadow_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "from_body_source",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of_expr",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of_expr",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of_stmt",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "source_fragment_of_stmt",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/type_decl.rs",
        "lift_enum_decl",
        "unwrap_or_default",
    ),
    (
        "unwrap_or_default",
        "implementations/rust/sugar-walk/src/type_decl.rs",
        "lift_impl_block",
        "unwrap_or_default",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "walk_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "walk_items_for_doc",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "walk_items_for_sig",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-lift/src/call_edges.rs",
        "collect_call_sites_in_expr",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-lift/src/call_edges.rs",
        "walk_items_for_edges",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_emit.rs",
        "find_fn_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "assert_no_fn_name_outside_gap_records",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "assert_no_forbidden_term_shape_fields",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "bind_option_pattern_type_id",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "bind_pattern_type_id",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "bind_pattern_type_id_direct",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_assignment_roots",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_bind_lift_targets_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_callsites_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_comment_surfaces",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_enum_variant_type_map_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_expr_roots",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_function_contract_targets_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_function_return_crates_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_local_free_function_names_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_local_type_names_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_op_cids",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_pat_bound_idents",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_pure_free_guard_facts",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_struct_field_type_map_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "collect_sugar_targets_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "find_item_fn_by_name",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "recognize_walk_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/contract.rs",
        "scan_expr_for_effects",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/emit.rs",
        "collect_ffi_declarations_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/emit.rs",
        "collect_proc_macro_invocations_from_item",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/emit.rs",
        "find_term_function_in_items",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "assertion_guard_for_partial",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "bind_pat_idents_lift",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "collect_assignment_roots_lift",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "collect_expr_roots_lift",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "collect_pat_bound_idents_lift",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "collect_pat_names",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "collect_statement_pure_free_guard_facts",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/lift.rs",
        "invalidate_assignment_targets",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "operand_place_to_ir_term",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        "collect_mutated_in_expr",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "first_balanced_parens",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "hover_markdown",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "collect_source_fns_in_scope",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/type_decl.rs",
        "lift_file_type_decls",
        "_ => {}",
    ),
    (
        "wildcard_empty_block",
        "implementations/rust/sugar-walk/src/walk.rs",
        "walk_expr_for_callsites",
        "_ => {}",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "classify_attr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "classify_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "classify_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "classify_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "classify_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "spec_b3_option_return_emits_is_some_or_is_none_predicate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        "spec_b3_result_return_emits_is_ok_or_is_err_predicate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-lift/src/call_edges.rs",
        "callee_name_from_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/hover_probe.rs",
        "main",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_demo.rs",
        "find_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "binary_operator_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "block_tail_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "call_expr_callee",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "channel_send_payload_zero_arg_producer",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "contract",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "evidence_role",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "evidence_role",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_as_call",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_bare_ident_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_constructed_type_identity",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_option_inner_type_identity",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_path_text",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_return_crate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "expr_type_identity",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "lift_post",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "literal_symbol",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "local_binding_ident_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "local_binding_ident_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "local_binding_sort",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "local_binding_symbol",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "mint_memento_for",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "mutex_guard_access_lock_site",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "mutex_guard_access_lock_site",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "mutex_lock_site",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "operand_symbol",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "panic_loci_for_first_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "panic_partial_for_receiver",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "panic_stem_for_post_predicate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "parse_attr_named_args",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "parse_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "pat_ident_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "pat_immutable_ident_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "pat_single_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "pat_type_identity",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "recognize_match_item_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "serde_json_panic_partial_for_receiver",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sort_from_type_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sugar_body_source_emits_template_cid_without_storing_template",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sugar_body_source_is_one_shape_without_inline_body_or_template",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sugar_body_template_canonicalizes_multiple_params_positionally",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sugar_original_param_types",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "sugar_param_types",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        "unary_operator_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/charon_runner.rs",
        "end_to_end_charon_runner_to_llbc_lift_to_cross_layer_equality",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/contract.rs",
        "parse_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/dropper/emit.rs",
        "find_caller",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/dropper/gap.rs",
        "detects_not_null_gap_at_function_entry",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/dropper/gap.rs",
        "no_gap_when_predicate_not_present",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/dropper/predicate.rs",
        "predicate_var_arg",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/dropper/verify.rs",
        "re_lift_confirms_closure_after_defensive_drop",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "arithmetic_binary_op",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "bitwise_binary_op",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "block_single_tail_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "comparison_op",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "concept_sort_from_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "local_pat_type",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "logical_binary_op",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "method_receiver_source_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "mut_borrow_source_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "parse_named",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "partial_return_loss",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "partial_return_loss",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/emit.rs",
        "sort_from_type_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/envelope.rs",
        "fixture_contract",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "assignment_root_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "bin_op_to_predicate_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "block_tail_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "branch_guard_head",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "expr_as_call_lift",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "expr_as_method_call_lift",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "expr_root_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "expr_string_literal",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "expr_string_literal",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "find_next_partial_receiver",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "keyset_source_from_borrowed_map_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "len_receiver_root_expr",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "len_receiver_term",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "lift_macro_contribution",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "lift_stmt_contribution",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "local_binding_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "local_binding_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "local_pat_single_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "negate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "next_into_iter_receiver_key",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "next_into_iter_receiver_key",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "parse_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "pat_single_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "receiver_producer_callsite_lift",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "token_string_literal",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/lift.rs",
        "tuple_first_pat_ident",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_calls.rs",
        "atomic_kind_for_method",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "cross_layer_compound_or_predicate_equality",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "cross_layer_predicate_equality_with_ast_walk",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "cross_layer_struct_field_byte_equality",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "cross_layer_tuple_field_byte_equality",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "mir_arith_op_to_ir_ctor",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "mir_binop_to_ir_predicate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/llbc_lift.rs",
        "negate_predicate",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/locus.rs",
        "locus_extracts_line_col_from_span",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        "parse_fn",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/marriage.rs",
        "build_layers",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/marriage.rs",
        "lift_marriage",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        "hover_markdown",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/shadow.rs",
        "parse_fn_local",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/signature.rs",
        "canonical_operation_name",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/source_oracle.rs",
        "param_names_without_receiver_from_signature",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/walk.rs",
        "collect_into",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/walk.rs",
        "let_binding",
        "_ => None",
    ),
    (
        "wildcard_none",
        "implementations/rust/sugar-walk/src/walk.rs",
        "parse_fn",
        "_ => None",
    ),
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct FrontierKey {
    file: String,
    enclosing_fn: String,
    observed: String,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct Site {
    kind: &'static str,
    key: FrontierKey,
    line: usize,
    replacement: &'static str,
}

#[derive(Debug, Clone)]
struct Report {
    offenders: Vec<Site>,
}

impl Report {
    fn total(&self) -> usize {
        self.offenders.len()
    }

    fn is_zero(&self) -> bool {
        self.offenders.is_empty()
    }

    fn vector(&self) -> BTreeMap<&'static str, usize> {
        let mut vector = BTreeMap::from([
            ("ok", 0),
            ("unwrap_or", 0),
            ("unwrap_or_default", 0),
            ("wildcard_empty_block", 0),
            ("wildcard_none", 0),
        ]);
        for site in &self.offenders {
            *vector.entry(site.kind).or_insert(0) += 1;
        }
        vector
    }

    fn keys_with_kind(&self) -> Vec<(&str, &str, &str, &str)> {
        self.offenders
            .iter()
            .map(|site| {
                (
                    site.kind,
                    site.key.file.as_str(),
                    site.key.enclosing_fn.as_str(),
                    site.key.observed.as_str(),
                )
            })
            .collect()
    }

    fn to_json(&self) -> String {
        let offenders = self
            .offenders
            .iter()
            .map(|site| {
                serde_json::json!({
                    "kind": site.kind,
                    "file": site.key.file,
                    "enclosing_fn": site.key.enclosing_fn,
                    "observed": site.key.observed,
                    "line": site.line,
                    "replacement": site.replacement,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&serde_json::json!({
            "total": self.total(),
            "is_zero": self.is_zero(),
            "vector": self.vector(),
            "offenders": offenders,
        }))
        .expect("serialize report")
    }

    fn to_expected_frontier_literal(&self) -> String {
        let mut out = String::new();
        out.push_str("const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[\n");
        for site in &self.offenders {
            out.push_str(&format!(
                "    ({:?}, {:?}, {:?}, {:?}),\n",
                site.kind, site.key.file, site.key.enclosing_fn, site.key.observed
            ));
        }
        out.push_str("];\n");
        out
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn collect_silent_drop_frontier(root: &Path) -> Result<Report, String> {
    let source_roots = [
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/sugar-lift/src"),
        root.join("implementations/rust/sugar-lift-contracts/src"),
        root.join("implementations/rust/sugar-lifter/src"),
    ];
    let mut offenders = Vec::new();
    for source_root in source_roots {
        let files = rust_files_under(&source_root)?;
        for path in files {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path)
                .map_err(|err| format!("read {}: {err}", path.display()))?;
            let parsed = syn::parse_file(&source).map_err(|err| format!("parse {rel}: {err}"))?;
            let lines = source.lines().map(str::to_string).collect::<Vec<_>>();
            let mut collector = Collector {
                file: rel,
                lines,
                fn_stack: Vec::new(),
                offenders: Vec::new(),
            };
            collector.visit_file(&parsed);
            offenders.extend(collector.offenders);
        }
    }
    offenders.sort();
    Ok(Report { offenders })
}

fn rust_files_under(root: &Path) -> Result<Vec<PathBuf>, String> {
    if !root.is_dir() {
        return Err(format!("source root missing: {}", root.display()));
    }
    let mut files = Vec::new();
    collect_rust_files(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_rust_files(dir: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    for entry in fs::read_dir(dir).map_err(|err| format!("read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| format!("read dir entry {}: {err}", dir.display()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_rust_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            files.push(path);
        }
    }
    Ok(())
}

struct Collector {
    file: String,
    lines: Vec<String>,
    fn_stack: Vec<String>,
    offenders: Vec<Site>,
}

impl Collector {
    fn enclosing_fn(&self) -> String {
        self.fn_stack
            .last()
            .cloned()
            .unwrap_or_else(|| "<module>".to_string())
    }

    fn is_sanctioned(&self, line: usize) -> bool {
        line.checked_sub(2)
            .and_then(|idx| self.lines.get(idx))
            .is_some_and(|line| {
                line.contains("sugar-audit: not-mine(") || line.contains("sugar-audit: default-ok(")
            })
    }

    fn push_site(
        &mut self,
        kind: &'static str,
        line: usize,
        observed: &'static str,
        replacement: &'static str,
    ) {
        if self.is_sanctioned(line) {
            return;
        }
        self.offenders.push(Site {
            kind,
            key: FrontierKey {
                file: self.file.clone(),
                enclosing_fn: self.enclosing_fn(),
                observed: observed.to_string(),
            },
            line,
            replacement,
        });
    }
}

impl<'ast> Visit<'ast> for Collector {
    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_impl_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_expr_match(&mut self, node: &'ast syn::ExprMatch) {
        for arm in &node.arms {
            if !matches!(arm.pat, syn::Pat::Wild(_)) {
                continue;
            }
            let line = arm.pat.span().start().line;
            if is_empty_block(&arm.body) {
                self.push_site(
                    "wildcard_empty_block",
                    line,
                    "_ => {}",
                    "replace silent catch-all with explicit variant handling or loud refusal",
                );
            } else if is_none_expr(&arm.body) {
                self.push_site(
                    "wildcard_none",
                    line,
                    "_ => None",
                    "replace silent classifier miss with explicit handling, refusal, or per-site sanction",
                );
            }
        }
        syn::visit::visit_expr_match(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        let method = node.method.to_string();
        let line = node.method.span().start().line;
        match method.as_str() {
            "unwrap_or" => self.push_site(
                "unwrap_or",
                line,
                "unwrap_or",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "unwrap_or_default" => self.push_site(
                "unwrap_or_default",
                line,
                "unwrap_or_default",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "ok" => self.push_site(
                "ok",
                line,
                "ok",
                "preserve the error, make the refusal loud, or mark the specific miss not-mine/default-ok",
            ),
            _ => {}
        }
        syn::visit::visit_expr_method_call(self, node);
    }
}

fn is_empty_block(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Block(block) if block.block.stmts.is_empty())
}

fn is_none_expr(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Path(path) if path.path.is_ident("None"))
}

#[test]
fn silent_drop_frontier_matches_expected_multiset() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    let observed = report.keys_with_kind();

    assert_eq!(
        observed,
        EXPECTED_FRONTIER,
        "silent-drop frontier changed\n{}\n\nPasteable EXPECTED_FRONTIER:\n{}",
        report.to_json(),
        report.to_expected_frontier_literal()
    );
}

#[test]
fn silent_drop_frontier_is_red_report_only() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    eprintln!("{}", report.to_json());

    assert!(
        !report.is_zero(),
        "frontier unexpectedly reached stable zero; remove the red report-only assertion"
    );
    assert_eq!(
        report.total(),
        EXPECTED_FRONTIER.len(),
        "{}",
        report.to_json()
    );
}

#[test]
#[ignore = "red target: run with --ignored to see the stable-zero failure until all silent-drop offenders are drained or sanctioned"]
fn silent_drop_frontier_stable_zero_target() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");

    assert!(report.is_zero(), "{}", report.to_json());
}
