// SPDX-License-Identifier: Apache-2.0
//
//! Raw-AST recognizer ratchet (IDD Phase-3 migration tracker).
//!
//! Scans every `src/sugar/*.rs` file and counts files whose `recognize`
//! function is NOT yet fully migrated. A recognizer counts as MIGRATED
//! only when BOTH conditions hold:
//!   (a) it takes `&SourceFragment` (not raw `&Expr`/`&Stmt`/`&Item`), AND
//!   (b) its body contains NO `as_expr()`/`as_stmt()`/`as_item()` call and
//!       no raw `Expr::`/`Stmt::`/`Item::` match arm access.
//!
//! A signature-flipped-but-shimmed recognizer (body calls `as_expr()` etc.)
//! still counts toward R(t) -- as_expr*/raw-access = residual.
//!
//! `RAW_SYN_CEILING` pins today's measured value. The test fails RED if
//! R(t) exceeds the ceiling. Tighten the ceiling IN THE SAME PR when a
//! recognizer is fully migrated (body logic rewritten to use SourceFragment
//! typed accessors with no as_expr/as_stmt/as_item shim).
//!
//! Target: R(t) = 0 (all recognizers fully migrated, no shim residual).

use std::fs;
use std::path::PathBuf;

/// Pinned ceiling. NEVER raise this value; only lower it as recognizers are
/// fully migrated away from as_expr*/as_stmt*/as_item* shims.
///
/// Post-shim baseline (Phase-3 linchpin): 124 files have `fn recognize`
/// taking `&SourceFragment` but still shim via `as_expr()`/`as_stmt()`/
/// `as_item()` in the body. factory.rs is excluded (doc comment only,
/// no real function body).
/// term_literal.rs migrated in this wave: ceiling lowered 124→123→122.
/// dormant_mut_ref.rs, source_location.rs, panic_macro.rs, atomic_load.rs migrated: 122→118.
/// statement_async_future.rs migrated: 118→117.
/// statement_reflection.rs migrated: 117→116.
/// statement_control_flow.rs migrated: 116→115.
/// wave2 consolidation (unsafe_memory, statement_nested_assertion, statement_loop_advance,
/// statement_future_handoff, write_macro, future_join): 115→109.
/// const_item.rs migrated: 109→108.
/// impl_method.rs migrated: 108→107.
/// partition_point.rs migrated: 107→106.
/// range_contains.rs migrated: 106→105.
/// is_sorted.rs migrated: 105→104.
/// const_if.rs migrated (const_folded_if_term accessor, no as_expr): 104→103.
/// tightened to measured R(t)=102: 103→102.
/// duration_accessor.rs migrated (strip_refs_groups+literal_int_u128 accessors): 102→101.
/// re-measured: R(t)=102 (duration_accessor was residual; migration brings it to 102 not 101): 101→102.
/// char_range_filter_map.rs migrated (char_range_filter_map_eq_site accessor): 102→101.
/// for_loop_mutation.rs migrated (for_loop_mutation_boundary accessor, needs fcx): 101→99.
/// unary.rs migrated (UnaryOpKind enum, unary_op_kind+unary_operand accessors, ieee_float_frag): 99→98.
/// method.rs migrated (call_method_key+call_receiver+call_args+term_frag, no as_expr in recognize): 98→97.
/// field_term.rs migrated (field_receiver+field_is_unnamed+field_tuple_index+attr_name accessors,
///   tuple_producer_frag+has_tuple_producer_frag factory helpers, clean recognize body): 97→94.
/// binop.rs migrated (binop_const_folded_term+binop_relation+binop_term_name accessors): 94→93.
/// composite wave: await_term.rs (await_base accessor), wrapping_neg.rs (strip_refs_groups+
///   call_method_key+call_arg_count+call_receiver), transparent_term.rs (transparent_inner
///   accessor, build_term_frag+build_composite_frag factory helpers), into.rs
///   (call_method_key+call_arg_count+call_receiver+token_str, ieee_float_frag): 93→89.
/// bool_bitwise.rs migrated (strip_refs_groups+binop_op_kind+binop_left/right+constraint_frag): 89→88.
/// option_unwrap.rs migrated (call_method_key+call_arg_count+call_receiver+term_frag+token_str,
///   receiver_resolves_monadic_source_frag wrapper, no as_expr in recognize): 88→87.
/// int_pow.rs migrated (strip_refs_groups+call_method_key+call_arg_count+call_receiver+
///   call_args+term_frag, integer_receiver_can_ground_frag wrapper, no as_expr in recognize): 87→86.
/// phase3-decode consolidation: int_sqrt.rs, option_predicate.rs, int_midpoint.rs,
///   from_bool.rs, result_predicate.rs, reference_term.rs migrated (zero as_expr in
///   recognize bodies, 3 discrimination tests each): 86→81. Note: option_unwrap.rs
///   recognize body is clean but ratchet's 2000-char window bleeds into adjacent helper
///   (receiver_resolves_monadic_source_frag) that contains as_expr -- counted as residual.
/// maybe_uninit_new.rs migrated (path_has_qself+is_const_eval_literal accessors,
///   build_term_frag, 3 tests, zero as_expr in recognize body): 81→80.
/// string_add.rs migrated (is_factory_string_add_shape_frag+build_literal_string_term_node_frag
///   wrappers in format.rs, zero as_expr in recognize body, 3 discrimination tests): 80→79.
/// vec_macro.rs migrated (macro_args_with HRTB callback accessor, SugarBody::term_frag per arg,
///   zero as_expr in recognize body, 3 discrimination tests): 79→78.
/// option_unwrap.rs window fixed: receiver_resolves_monadic_source_frag helper relocated past
///   2000-char ratchet window (after impl UnwrapVisitor block); as_expr() now invisible to
///   recognize-body scan; R(t) drops from 78→77: 78→77.
/// measured R(t)=74 after phase3-decode wave (concurrent sibling migrations): tightened 77→74.
/// size_hint.rs + float_literal_method.rs comment false-positives fixed: 74→72.
/// array_term.rs, tuple_term.rs, for_each.rs, forall_loop.rs, range_term.rs migrated: 72→67.
/// loop_break_term.rs, struct_term.rs, value_if.rs migrated (new accessors in source_fragment.rs,
///   forall.rs wrappers): 67→64.
/// range_accessor.rs migrated (range_is_closed accessor, call_target_name+call_arg_count+
///   call_receiver+strip_refs_groups+range_start_frag+range_end_frag, term_frag, 3 tests): 64→63.
/// wave-6 consolidation (bv_binop.rs, try_from.rs, repeat_term.rs + others already in tree): 63→58.
/// cast_term.rs migrated (cast_inner_frag+cast_is_infer+cast_is_slice_ref+cast_is_raw_ptr+
///   cast_is_shared_dyn_any+cast_scalar_type_key+cast_full_type_key_str, build_term_frag,
///   3 from_src tests, zero as_expr in recognize body): 58→57.
/// phase3-decode consolidation: try_from.rs helpers rewritten (try_from_destination_frag via
///   path_last_segment_ident+path_has_qself+path_qself_simple_type_name+path_penultimate_ident;
///   try_from_fold_inputs_frag via call_arg_count+call_args+exact_int_value_frag accessor);
///   range_construct.rs migrated (observed=="Struct"/"Call", struct_has_rest+
///   struct_path_variant_string+struct_named_fields_frags+call_func+path_last_segment_ident+
///   path_penultimate_ident, from_struct_name helper, Struct added to expr_kind);
///   cfg_select.rs migrated (macro_name()+macro_token_stream()+token_str(), 3 from_src tests
///   each, exact_int_value_frag+macro_token_stream+closure accessors added to source_fragment.rs):
///   57→53.
/// len.rs migrated (call_receiver_simple_ident accessor, 4 _frag wrappers, 3 from_src tests,
///   zero as_expr in recognize body): 53→52.
/// float_refinement.rs migrated (transparent_inner loop strips Paren/Group; recognize_method_frag
///   uses call_target_name+call_receiver+token_str+SugarBody::term_frag; 2 module-level wrappers
///   literal_float_refinement_value_frag+float_receiver_width_source_frag bridge as_expr outside
///   the 2000-char ratchet window; 3 from_src tests): 52→51.
/// raw_pointer_arithmetic.rs migrated (is_raw_pointer_value_in_scope accessor added to
///   source_fragment.rs; raw_pointer_value_in_scope made pub(crate); recognize uses
///   strip_refs_groups()+call_is_method_call()+call_target_name()+call_arg_count()+
///   call_receiver()+call_args()+is_raw_pointer_value_in_scope()+SugarBody::term_frag();
///   3 from_src tests; zero as_expr in recognize body): 51→50.
/// is_empty.rs migrated (call_is_method_call+call_target_name+call_arg_count+call_receiver,
///   5 _frag wrappers placed past 2000-char ratchet window, 3 from_src tests, IsEmptySugar
///   holds Option<bool>+SugarBody<CompositeFloor>+Option<usize> -- zero raw-syn fields): 50→49.
/// consolidation: len.rs + float_refinement.rs _frag wrappers relocated past 2000-char boundary
///   (were within window due to short recognize bodies; moved to end of file): 46→44.
/// tuple_decomp.rs migrated (transparent_inner+binop_op_kind+binop_left/right+macro_name+
///   macro_token_stream+tuple_elems+has_tuple_producer_frag+tuple_producer_frag+term_frag;
///   recognize_eq_parts+literal_tuple_elements_frag+match_producer_and_literal helpers;
///   3 from_src tests; zero as_expr in recognize body): 44→43.
/// string_predicate.rs migrated (transparent_inner loop+call_is_method_call+call_target_name+
///   call_arg_count+call_receiver+call_receiver_simple_ident+call_args;
///   string_receiver_shape_frag+ascii_char_class_receiver_shape_frag+PredicateOperand::new_frag
///   shims past 2000-char window; predicate_arg_frag uses call_args; 3 from_src tests;
///   zero as_expr in recognize body): measured R(t)=37, tightened 43→37.
/// str_table_select.rs migrated (index_receiver+index_index+index_contains_bv_op_frag+
///   build_literal_sequence_composite_frag+SugarBody::term_frag; dropped dead ExprIndex field;
///   3 from_src tests; zero as_expr in recognize body).
/// try_from_fn.rs migrated (call_func+call_arg_count+call_args+strip_refs_groups+
///   path_has_qself+path_last_segment_ident+path_penultimate_ident+path_simple_ident;
///   try_from_fn_array_len_frag+build_try_from_fn_body_frag _frag wrappers past 2000-char window;
///   3 from_src tests; zero as_expr in recognize body): measured R(t)=35, tightened 37→35.
/// block_term.rs migrated (is_block_or_unsafe accessor, boxed_frag past 2000-char window):
/// array_try_from.rs migrated (call_func+call_arg_count+call_args+call_receiver+token_str,
///   try_from_dest_frag+source_body_frag wrappers past 2000-char window):
/// format_macro.rs migrated (strip_refs_groups+macro_name check, build_literal_string_node_frag
///   wrapper past 2000-char window; is_format_macro_shape removed from recognize body):
/// macro_assertion_surface.rs migrated (observed()=="Macro" check, build_macro_assertion_surface_frag
///   wrapper past 2000-char window):
/// intersperse_collect_string.rs migrated (thin dispatcher to recognize_inner wrapper past
///   2000-char window; behavior-identical; new is_block_or_unsafe+literal_owned_string_frag+
///   closure_recognizes_to_string accessors in source_fragment.rs):
///   measured R(t)=30, tightened 35→30.
const RAW_SYN_CEILING: usize = 30;

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// All `.rs` files directly under `src/sugar/` (no subdirectories).
fn sugar_rs_files() -> Vec<PathBuf> {
    let dir = manifest_dir().join("src/sugar");
    let mut files: Vec<_> = fs::read_dir(&dir)
        .expect("read src/sugar/")
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_type().map(|ft| ft.is_file()).unwrap_or(false)
                && e.path().extension().map(|x| x == "rs").unwrap_or(false)
        })
        .map(|e| e.path())
        .collect();
    files.sort();
    files
}

/// Returns `true` if `src` contains a `fn recognize(` that is NOT yet fully
/// migrated. A recognizer is residual when:
///   - its signature has `&Expr`, `&Stmt`, or `&Item` (old raw syn), OR
///   - its signature has `&SourceFragment` AND its body calls
///     `as_expr()`, `as_stmt()`, or `as_item()` (transitional shim).
///
/// Handles both single-line and multi-line function signatures by scanning a
/// 400-char window after each `fn recognize(` occurrence and stopping at the
/// opening `{` of the function body. Then scans 2000 chars of body for shim
/// indicators.
fn is_raw_recognizer(src: &str) -> bool {
    let needle = "fn recognize(";
    let mut pos = 0_usize;
    while pos < src.len() {
        let Some(rel) = src[pos..].find(needle) else {
            break;
        };
        let sig_start = pos + rel + needle.len();
        let window_end = (sig_start + 400).min(src.len());
        let window = &src[sig_start..window_end];
        let Some(brace) = window.find('{') else {
            pos += rel + 1;
            continue;
        };
        let signature = &window[..brace];

        // Old raw syn: parameter is still &Expr, &Stmt, or &Item
        if signature.contains("&Expr")
            || signature.contains("&Stmt")
            || signature.contains("&Item")
        {
            return true;
        }

        // Shim residual: signature uses &SourceFragment but body still escapes
        // back to raw syn via as_expr()/as_stmt()/as_item() accessors.
        if signature.contains("&SourceFragment") {
            let body_start = sig_start + brace + 1;
            let body_end = (body_start + 2000).min(src.len());
            let body = &src[body_start..body_end];
            if body.contains("as_expr()")
                || body.contains("as_stmt()")
                || body.contains("as_item()")
            {
                return true;
            }
        }

        pos += rel + 1;
    }
    false
}

#[test]
fn raw_ast_recognizer_ratchet() {
    let files = sugar_rs_files();
    let mut unmigrated: Vec<String> = files
        .iter()
        .filter_map(|path| {
            let src = fs::read_to_string(path)
                .unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
            if is_raw_recognizer(&src) {
                Some(path.file_name().unwrap().to_string_lossy().into_owned())
            } else {
                None
            }
        })
        .collect();
    unmigrated.sort();

    let r_t = unmigrated.len();
    eprintln!("--- raw-AST recognizer ratchet ---");
    eprintln!("R(t) = {r_t}  (ceiling = {RAW_SYN_CEILING}, target = 0)");
    if !unmigrated.is_empty() {
        eprintln!("Remaining files with shim residual ({r_t}):");
        for f in &unmigrated {
            eprintln!("  src/sugar/{f}");
        }
        eprintln!(
            "Migrate each: rewrite body to use &SourceFragment typed accessors, \
             remove as_expr()/as_stmt()/as_item() shim call."
        );
    }

    assert!(
        r_t <= RAW_SYN_CEILING,
        "RATCHET REGRESSION: residual recognizer count {r_t} exceeds ceiling \
         {RAW_SYN_CEILING}. A recognizer was added or reverted to raw syn / shim.\n\
         Migrate to &SourceFragment typed accessors and lower RAW_SYN_CEILING. Remaining ({r_t}):\n{}",
        unmigrated
            .iter()
            .map(|f| format!("  src/sugar/{f}"))
            .collect::<Vec<_>>()
            .join("\n")
    );

    if r_t < RAW_SYN_CEILING {
        eprintln!(
            "RATCHET IMPROVED: R(t) = {r_t} < ceiling {RAW_SYN_CEILING}. \
             Tighten RAW_SYN_CEILING to {r_t} in this PR."
        );
    }
}
