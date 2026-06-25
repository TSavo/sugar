use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Clone)]
struct FunctionSpan {
    name: String,
    start_line: usize,
    end_line: usize,
}

#[derive(Debug, Clone)]
struct Offender {
    axis: &'static str,
    line: usize,
    key: String,
    symbol: String,
    action: &'static str,
}

#[derive(Debug, Clone, Copy)]
struct ReplacementPlan {
    module: &'static str,
    sugar: &'static str,
    role: &'static str,
    claim: &'static str,
    recognizer: &'static str,
    desugar: &'static str,
    floors: &'static [&'static str],
    delete_from_lib: &'static [&'static str],
    focused_test: &'static str,
}

#[test]
fn lib_gravity_delta_epsilon_vector_is_zero() {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let lib_path = manifest.join("src/lib.rs");
    let src = fs::read_to_string(&lib_path)
        .unwrap_or_else(|err| panic!("read {}: {err}", lib_path.display()));
    let functions = function_spans(&src);

    let mut offenders = Vec::new();
    offenders.extend(inline_sugar_impls(&src));
    offenders.extend(legacy_translate_functions(&functions));
    offenders.extend(legacy_semantic_emitters(&functions));
    offenders.extend(late_factory_reopens(&src, &functions));

    offenders.sort_by_key(|offender| (offender.line, offender.axis, offender.symbol.clone()));

    let mut counts = BTreeMap::<&'static str, usize>::new();
    for offender in &offenders {
        *counts.entry(offender.axis).or_default() += 1;
    }

    assert!(
        offenders.is_empty(),
        "lib gravity delta-epsilon R vector is not stable zero.\n\
         This test is intentionally red until every listed lib.rs offender is moved into \
         tiny Sugar/floor-owned code. Each PR must lower one or more counts; never loosen \
         this test except in an explicit accounting-correction PR.\n\
         Every offender must carry a replacement plan; UNPLANNED means the test found \
         lib gravity without a named sugar migration.\n\n\
         R = {}\n\n{}",
        render_counts(&counts),
        render_offenders(&offenders)
    );
}

fn function_spans(src: &str) -> Vec<FunctionSpan> {
    let parsed = syn::parse_file(src).expect("src/lib.rs must parse as Rust");
    let mut spans = Vec::new();
    for item in parsed.items {
        match item {
            syn::Item::Fn(item) => spans.push(FunctionSpan {
                name: item.sig.ident.to_string(),
                start_line: item.sig.fn_token.span.start().line,
                end_line: item.block.brace_token.span.close().end().line,
            }),
            syn::Item::Impl(item) => {
                let owner = impl_type_name(&item.self_ty);
                for impl_item in item.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        spans.push(FunctionSpan {
                            name: format!("{}::{}", owner, method.sig.ident),
                            start_line: method.sig.fn_token.span.start().line,
                            end_line: method.block.brace_token.span.close().end().line,
                        });
                    }
                }
            }
            _ => {}
        }
    }
    spans
}

fn impl_type_name(ty: &syn::Type) -> String {
    match ty {
        syn::Type::Path(path) => path
            .path
            .segments
            .last()
            .map(|segment| segment.ident.to_string())
            .unwrap_or_else(|| "impl".to_string()),
        syn::Type::Reference(reference) => impl_type_name(&reference.elem),
        _ => "impl".to_string(),
    }
}

fn inline_sugar_impls(src: &str) -> Vec<Offender> {
    src.lines()
        .enumerate()
        .filter_map(|(idx, line)| {
            line.contains("impl Sugar for").then(|| Offender {
                axis: "inline_sugar_impls_in_lib",
                line: idx + 1,
                key: inline_sugar_key(line),
                symbol: line.trim().to_string(),
                action: "move the Sugar impl into src/sugar/<domain>.rs and register its claim",
            })
        })
        .collect()
}

fn inline_sugar_key(line: &str) -> String {
    line.split("impl Sugar for")
        .nth(1)
        .and_then(|tail| tail.split('{').next())
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(|name| format!("inline:{name}"))
        .unwrap_or_else(|| format!("inline:{}", line.trim()))
}

fn legacy_translate_functions(functions: &[FunctionSpan]) -> Vec<Offender> {
    functions
        .iter()
        .filter(|span| {
            span.name.starts_with("translate_") || span.name.starts_with("try_translate_")
        })
        .map(|span| Offender {
            axis: "legacy_translate_functions_in_lib",
            line: span.start_line,
            key: format!("fn:{}", span.name),
            symbol: span.name.clone(),
            action: "replace the adapter with a Sugar/floor-owned implementation and delete the lib.rs helper",
        })
        .collect()
}

fn legacy_semantic_emitters(functions: &[FunctionSpan]) -> Vec<Offender> {
    let targets: BTreeSet<&str> = [
        "emit_bool_membership_formula",
        "emit_callable_param_precondition_contract",
        "emit_guard_return_value",
        "emit_if_value",
        "emit_match_value",
        "emit_slice_pattern_membership",
        "emit_source_assertion_contract",
        "source_value_contract",
    ]
    .into_iter()
    .collect();

    functions
        .iter()
        .filter(|span| targets.contains(span.name.as_str()))
        .map(|span| Offender {
            axis: "legacy_semantic_emitters_in_lib",
            line: span.start_line,
            key: format!("fn:{}", span.name),
            symbol: span.name.clone(),
            action: "move source-value emission behind a Sugar/floor-owned domain expert",
        })
        .collect()
}

fn late_factory_reopens(src: &str, functions: &[FunctionSpan]) -> Vec<Offender> {
    let allowed_source_boundaries: BTreeSet<&str> = [
        "collect_constraint_expr",
        "collect_source_assertion_contract_expr",
        "collect_statement_macro_entries",
        "emit_panic_freedom_callsites_in_stmt",
    ]
    .into_iter()
    .collect();

    let mut offenders = Vec::new();
    let mut occurrences = BTreeMap::<String, usize>::new();
    for (idx, line) in src.lines().enumerate() {
        let line_no = idx + 1;
        let trimmed = line.trim();
        let owner = current_function(functions, line_no);
        if trimmed.starts_with("//")
            || !trimmed.contains("sugar::factory::build_")
            || owner.is_some_and(|name| allowed_source_boundaries.contains(name))
        {
            continue;
        }
        let owner = owner.unwrap_or("<unknown>");
        let occurrence_key = format!("{owner}:{trimmed}");
        let occurrence = occurrences.entry(occurrence_key).or_default();
        *occurrence += 1;
        offenders.push(Offender {
            axis: "late_factory_reopens_in_lib",
            line: line_no,
            key: factory_reopen_key(owner, trimmed, *occurrence),
            symbol: trimmed.to_string(),
            action: "construct typed SugarBody children during recognition, or move this source boundary out of lib.rs",
        });
    }
    offenders
}

fn current_function<'a>(functions: &'a [FunctionSpan], line: usize) -> Option<&'a str> {
    functions
        .iter()
        .find(|span| span.start_line <= line && line <= span.end_line)
        .map(|span| span.name.as_str())
}

fn factory_reopen_key(owner: &str, symbol: &str, occurrence: usize) -> String {
    match (owner, symbol, occurrence) {
        (
            "SugarCtx::opaque_callsite_term",
            "sugar::factory::build_term(expr, &fcx).reduce(&child)",
            1,
        ) => "late:SugarCtx::opaque_callsite_term:child_term".to_string(),
        (
            "SugarCtx::try_inline_value_call",
            "let node = sugar::factory::build_term(&inlined, &fcx);",
            1,
        ) => "late:SugarCtx::try_inline_value_call:inlined_body_term".to_string(),
        (
            "collect_assertion_entries",
            "Some(sugar::factory::build_composite(&init.expr, &fcx).desugar(&ctx))",
            1,
        ) => "late:collect_assertion_entries:let_initializer_composite".to_string(),
        ("collect_assertion_entries", "sugar::factory::build_composite(e, &fcx)", 1) => {
            "late:collect_assertion_entries:for_loop_composite".to_string()
        }
        ("collect_assertion_entries", "sugar::factory::build_composite(&synth_for, &fcx)", 1) => {
            "late:collect_assertion_entries:while_replay_composite".to_string()
        }
        ("collect_assertion_entries", "sugar::factory::build_composite(e, &fcx)", 2) => {
            "late:collect_assertion_entries:conditional_composite".to_string()
        }
        ("collect_assertion_entries", "sugar::factory::build_composite(e, &fcx)", 3) => {
            "late:collect_assertion_entries:match_composite".to_string()
        }
        ("collect_assertion_entries", "sugar::factory::build_composite(e, &fcx)", 4) => {
            "late:collect_assertion_entries:statement_composite".to_string()
        }
        (
            "translate_term_in_scope_with_audits",
            "let node = sugar::factory::build_term(expr, &fcx);",
            1,
        ) => "late:translate_term_in_scope_with_audits:term_dispatch".to_string(),
        _ => format!("late:{owner}:{symbol}#{occurrence}"),
    }
}

fn render_counts(counts: &BTreeMap<&'static str, usize>) -> String {
    if counts.is_empty() {
        return "{}".to_string();
    }
    counts
        .iter()
        .map(|(axis, count)| format!("{axis}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn render_offenders(offenders: &[Offender]) -> String {
    offenders
        .iter()
        .map(|offender| {
            let plan = replacement_plan(&offender.key)
                .map(|plan| render_plan(&offender.key, plan))
                .unwrap_or_else(|| {
                    format!("  UNPLANNED: add a replacement plan for {}", offender.key)
                });
            format!(
                "src/lib.rs:{} [{}] {} -> {}\n{}",
                offender.line, offender.axis, offender.symbol, offender.action, plan
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn render_plan(key: &str, plan: ReplacementPlan) -> String {
    format!(
        "  plan key: {key}\n\
         replacement sugar: {} in {}\n\
         role/claim: {} / {}\n\
         recognizer: {}\n\
         desugar: {}\n\
         delegate floors: {}\n\
         delete from lib.rs: {}\n\
         focused test: {}",
        plan.sugar,
        plan.module,
        plan.role,
        plan.claim,
        plan.recognizer,
        plan.desugar,
        list(plan.floors),
        list(plan.delete_from_lib),
        plan.focused_test
    )
}

fn list(items: &[&str]) -> String {
    if items.is_empty() {
        return "none".to_string();
    }
    items.join("; ")
}

fn replacement_plan(key: &str) -> Option<ReplacementPlan> {
    match key {
        "inline:ConfigGateSugar" => Some(configuration_gate_plan()),
        "fn:translate_bool_assertion"
        | "fn:translate_bool_assertion_with_audits"
        | "fn:translate_binary_bool_assertion"
        | "fn:translate_binary_bool_assertion_with_audits" => Some(bool_assertion_plan()),
        "fn:translate_float_refinement_assertion" => Some(float_refinement_plan()),
        "fn:translate_infinity_eq_assertion" | "fn:translate_infinity_eq_assertion_with_audits" => {
            Some(infinity_eq_plan())
        }
        "fn:translate_pointer_eq_assertion" => Some(pointer_eq_plan()),
        "fn:translate_pointer_identity_term" => Some(pointer_identity_plan()),
        "fn:translate_matches_assertion" => Some(matches_macro_plan()),
        "fn:translate_string_predicate_assertion" => Some(string_predicate_plan()),
        "fn:translate_regex_match_assertion" => Some(regex_match_plan()),
        "fn:translate_literal_iterator_assertion" => Some(literal_iterator_plan()),
        "fn:translate_term_in_scope" | "fn:translate_term_in_scope_with_audits" => {
            Some(term_dispatch_plan())
        }
        "fn:translate_assertion_term_in_scope"
        | "fn:translate_assertion_term_in_scope_with_audits" => Some(assertion_term_plan()),
        "fn:translate_expression_only_block_in_scope"
        | "fn:translate_expression_only_block_in_scope_with_audits" => Some(block_term_plan()),
        "fn:translate_lit" => Some(term_literal_plan()),
        "fn:emit_source_assertion_contract"
        | "fn:emit_callable_param_precondition_contract"
        | "fn:source_value_contract" => Some(source_contract_plan()),
        "fn:emit_guard_return_value" => Some(guard_return_plan()),
        "fn:emit_match_value" => Some(match_value_plan()),
        "fn:emit_if_value" => Some(if_value_plan()),
        "fn:emit_bool_membership_formula" => Some(bool_membership_plan()),
        "fn:emit_slice_pattern_membership" => Some(slice_pattern_plan()),
        "late:SugarCtx::opaque_callsite_term:child_term" => Some(opaque_callsite_child_plan()),
        "late:SugarCtx::try_inline_value_call:inlined_body_term" => Some(value_call_inline_plan()),
        "late:collect_assertion_entries:let_initializer_composite" => Some(let_initializer_plan()),
        "late:collect_assertion_entries:for_loop_composite" => Some(for_loop_plan()),
        "late:collect_assertion_entries:while_replay_composite" => Some(while_replay_plan()),
        "late:collect_assertion_entries:conditional_composite" => Some(conditional_plan()),
        "late:collect_assertion_entries:match_composite" => Some(match_composite_plan()),
        "late:collect_assertion_entries:statement_composite" => Some(statement_composite_plan()),
        "late:translate_term_in_scope_with_audits:term_dispatch" => Some(term_dispatch_plan()),
        _ => None,
    }
}

fn configuration_gate_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/configuration.rs",
        sugar: "ConfigGateSugar",
        role: "statement/configuration boundary",
        claim: "registered configuration claim",
        recognizer: "recognize cfg-gated attributes at factory time and capture the guarded child bodies",
        desugar: "delegate active children to the statement/composite floors; name inactive cfg residue as an effect",
        floors: &["statement floor", "composite floor"],
        delete_from_lib: &["inline impl Sugar for ConfigGateSugar"],
        focused_test: "this delta-epsilon test plus existing cfg/configuration lift coverage",
    }
}

fn bool_assertion_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/constraint.rs",
        sugar: "BoolAssertionSugar",
        role: "assertion constraint",
        claim: "assert/assert_eq bool constraint claim",
        recognizer: "recognize bool-valued assertion surfaces and capture lhs/rhs/operand as TermFloor children",
        desugar: "compose the boolean Formula through BoolFloor and ConstraintFloor instead of returning lib.rs AssertionEntry glue",
        floors: &["BoolFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &[
            "translate_bool_assertion*",
            "translate_binary_bool_assertion*",
        ],
        focused_test: "cargo test -p sugar-lift-rust-tests bool_assertion -- --nocapture",
    }
}

fn float_refinement_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/float_refinement.rs",
        sugar: "FloatRefinementSugar",
        role: "assertion constraint",
        claim: "float refinement assertion claim",
        recognizer: "recognize finite/is_nan/is_infinite float predicate assertions and capture the receiver term",
        desugar: "delegate numeric interpretation to the float floor and emit the refinement Formula from the sugar",
        floors: &["FloatFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_float_refinement_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests float_refinement -- --nocapture",
    }
}

fn infinity_eq_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/infinity_eq.rs",
        sugar: "InfinityEqSugar",
        role: "assertion constraint",
        claim: "infinity equality assertion claim",
        recognizer: "recognize equality against +/- infinity and capture both comparison operands",
        desugar: "ask FloatFloor for the infinity witness and emit equality/inequality through ConstraintFloor",
        floors: &["FloatFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_infinity_eq_assertion*"],
        focused_test: "cargo test -p sugar-lift-rust-tests infinity_eq -- --nocapture",
    }
}

fn pointer_eq_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/raw_addr_term.rs",
        sugar: "PointerEqAssertionSugar",
        role: "assertion constraint",
        claim: "pointer equality assertion claim",
        recognizer: "recognize ptr::eq/assert pointer identity forms and capture pointee address terms",
        desugar: "delegate address construction to the pointer term floor and emit equality as a constraint",
        floors: &["TermFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_pointer_eq_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests pointer_eq -- --nocapture",
    }
}

fn pointer_identity_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/raw_addr_term.rs",
        sugar: "PointerIdentityTermSugar",
        role: "term",
        claim: "pointer identity term claim",
        recognizer: "recognize raw/reference address identity expressions and capture the pointed expression",
        desugar: "emit the canonical address/identity Term through the term floor; bail on runtime ownership gaps",
        floors: &["TermFloor"],
        delete_from_lib: &["translate_pointer_identity_term"],
        focused_test: "cargo test -p sugar-lift-rust-tests pointer_identity -- --nocapture",
    }
}

fn matches_macro_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/matches_macro.rs",
        sugar: "MatchesMacroSugar",
        role: "assertion constraint",
        claim: "matches! assertion claim",
        recognizer:
            "recognize matches!(expr, pat) under an assertion and capture scrutinee/pattern shape",
        desugar:
            "delegate scrutinee terms to TermFloor and pattern membership to the pattern floor",
        floors: &["TermFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_matches_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests matches_macro -- --nocapture",
    }
}

fn string_predicate_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/string_predicate.rs",
        sugar: "StringPredicateAssertionSugar",
        role: "assertion constraint",
        claim: "string predicate assertion claim",
        recognizer: "recognize starts_with/ends_with/contains/is_empty string assertions and capture receiver/needle terms",
        desugar: "delegate literal/string facts to the string predicate sugar and emit the boolean constraint",
        floors: &["TermFloor", "BoolFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_string_predicate_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests string_predicate -- --nocapture",
    }
}

fn regex_match_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/regex_match.rs",
        sugar: "RegexMatchAssertionSugar",
        role: "assertion constraint",
        claim: "regex match assertion claim",
        recognizer: "recognize Regex::new literal patterns and is_match assertions",
        desugar: "delegate literal regex/string interpretation to the regex sugar and emit membership constraints",
        floors: &["TermFloor", "BoolFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_regex_match_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests regex_match -- --nocapture",
    }
}

fn literal_iterator_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/literal_iterator_quantifier.rs",
        sugar: "LiteralIteratorAssertionSugar",
        role: "assertion constraint",
        claim: "literal iterator quantifier claim",
        recognizer: "recognize all/any/find-style assertions over literal finite iterator domains",
        desugar: "delegate domain construction to SequenceFloor and reduce body assertions through BoolFloor/ConstraintFloor",
        floors: &["SequenceFloor", "BoolFloor", "ConstraintFloor"],
        delete_from_lib: &["translate_literal_iterator_assertion"],
        focused_test: "cargo test -p sugar-lift-rust-tests literal_iterator -- --nocapture",
    }
}

fn term_dispatch_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/term_dispatch.rs",
        sugar: "TermDispatchSugar",
        role: "term adapter boundary",
        claim: "fallback term dispatch claim",
        recognizer: "let the factory select the precise term sugar and keep only a thin external API shim if callers still need the old name",
        desugar: "run the selected child sugar through TermFloor and surface named Incomplete effects verbatim",
        floors: &["TermFloor"],
        delete_from_lib: &[
            "translate_term_in_scope*",
            "late build_term adapter call in translate_term_in_scope_with_audits",
        ],
        focused_test: "cargo test -p sugar-lift-rust-tests term_dispatch -- --nocapture",
    }
}

fn assertion_term_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/term_dispatch.rs",
        sugar: "AssertionTermSugar",
        role: "assertion operand term",
        claim: "assertion operand term claim",
        recognizer:
            "recognize assertion operand terms through the same factory-owned term claim stack",
        desugar:
            "reduce to TermFloor and preserve assertion-specific audit metadata outside lib.rs",
        floors: &["TermFloor"],
        delete_from_lib: &["translate_assertion_term_in_scope*"],
        focused_test: "cargo test -p sugar-lift-rust-tests assertion_term -- --nocapture",
    }
}

fn block_term_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/block_term.rs",
        sugar: "ExpressionOnlyBlockSugar",
        role: "term",
        claim: "expression-only block term claim",
        recognizer: "recognize blocks whose value is a single expression and capture the value expression as a child term",
        desugar: "delegate the value expression to TermFloor and name non-expression statement residue as an effect",
        floors: &["TermFloor"],
        delete_from_lib: &["translate_expression_only_block_in_scope*"],
        focused_test: "cargo test -p sugar-lift-rust-tests block_term -- --nocapture",
    }
}

fn term_literal_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/term_literal.rs",
        sugar: "LiteralTermSugar",
        role: "term",
        claim: "literal term claim",
        recognizer: "recognize ExprLit directly in the term factory",
        desugar: "emit canonical literal terms from the term floor and leave no lib.rs literal translator",
        floors: &["TermFloor"],
        delete_from_lib: &["translate_lit"],
        focused_test: "cargo test -p sugar-lift-rust-tests term_literal -- --nocapture",
    }
}

fn source_contract_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/source_contract.rs",
        sugar: "SourceContractSugar",
        role: "source contract",
        claim: "function source contract claim",
        recognizer: "recognize source-backed pre/postcondition bodies and capture their assertion/value children",
        desugar: "compose ContractDecls from floor-owned Formula terms instead of lib.rs emission helpers",
        floors: &["TermFloor", "BoolFloor", "ConstraintFloor"],
        delete_from_lib: &[
            "emit_source_assertion_contract",
            "emit_callable_param_precondition_contract",
            "source_value_contract",
        ],
        focused_test: "cargo test -p sugar-lift-rust-tests source_contract -- --nocapture",
    }
}

fn guard_return_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/source_contract.rs",
        sugar: "GuardReturnValueSugar",
        role: "source contract value",
        claim: "guarded return value claim",
        recognizer: "recognize guard-return bodies and capture guard/value expressions",
        desugar: "delegate guard to BoolFloor and returned value to TermFloor, then emit the implication formula",
        floors: &["BoolFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["emit_guard_return_value"],
        focused_test: "cargo test -p sugar-lift-rust-tests source_contract -- --nocapture",
    }
}

fn match_value_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/match_node.rs",
        sugar: "MatchValueSugar",
        role: "source contract value",
        claim: "match value claim",
        recognizer:
            "recognize source-value match expressions and capture scrutinee plus arm value formulas",
        desugar:
            "delegate discriminants to MatchSugar/pattern floors and emit guarded arm formulas",
        floors: &["TermFloor", "ConstraintFloor"],
        delete_from_lib: &["emit_match_value"],
        focused_test: "cargo test -p sugar-lift-rust-tests match_node -- --nocapture",
    }
}

fn if_value_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/conditional.rs",
        sugar: "IfValueSugar",
        role: "source contract value",
        claim: "if value claim",
        recognizer: "recognize source-value if expressions and capture condition/branch values",
        desugar: "delegate condition to BoolFloor and branches to source-value children, emitting guarded formulas",
        floors: &["BoolFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["emit_if_value"],
        focused_test: "cargo test -p sugar-lift-rust-tests conditional -- --nocapture",
    }
}

fn bool_membership_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/bool_predicate.rs",
        sugar: "BoolMembershipSugar",
        role: "source contract value",
        claim: "bool membership formula claim",
        recognizer: "recognize boolean membership expressions and capture the value term",
        desugar: "delegate to BoolFloor and emit the membership Formula from the sugar",
        floors: &["BoolFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["emit_bool_membership_formula"],
        focused_test: "cargo test -p sugar-lift-rust-tests bool_predicate -- --nocapture",
    }
}

fn slice_pattern_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/literal_slice.rs",
        sugar: "SlicePatternMembershipSugar",
        role: "source contract value",
        claim: "slice pattern membership claim",
        recognizer: "recognize slice pattern membership shapes and capture slice/pattern children",
        desugar:
            "delegate literal slice construction to SequenceFloor and emit membership constraints",
        floors: &["SequenceFloor", "TermFloor", "ConstraintFloor"],
        delete_from_lib: &["emit_slice_pattern_membership"],
        focused_test: "cargo test -p sugar-lift-rust-tests literal_slice -- --nocapture",
    }
}

fn opaque_callsite_child_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/callsite.rs",
        sugar: "OpaqueCallsiteSubjectSugar",
        role: "panic callsite subject",
        claim: "callsite subject support claim",
        recognizer: "recognize panic-freedom call/method subjects and capture receiver/argument children at construction",
        desugar: "reduce child terms through TermFloor, falling back to opaque callsite identity only at named boundaries",
        floors: &["TermFloor"],
        delete_from_lib: &["SugarCtx::opaque_callsite_term child factory recursion"],
        focused_test: "cargo test -p sugar-lift-rust-tests panic_callsite -- --nocapture",
    }
}

fn value_call_inline_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/call.rs",
        sugar: "ValueCallInlineSugar",
        role: "term inline support",
        claim: "grounded value-call inline claim",
        recognizer: "recognize visible pure value-call bodies and capture the substituted return expression as a child term",
        desugar: "delegate the substituted body to TermFloor, commit only when exact-or-bail grounding succeeds",
        floors: &["TermFloor"],
        delete_from_lib: &["SugarCtx::try_inline_value_call factory rebuild"],
        focused_test: "cargo test -p sugar-lift-rust-tests value_call_inline -- --nocapture",
    }
}

fn let_initializer_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/let_stmt.rs",
        sugar: "LetInitializerCompositeSugar",
        role: "statement composite",
        claim: "let-initializer composite claim",
        recognizer: "recognize constructible let initializer expressions and capture the initializer composite child",
        desugar: "delegate initializer asserts to CompositeFloor, preserving named terminal effects for non-top-level assertions",
        floors: &["CompositeFloor", "ConstraintFloor"],
        delete_from_lib: &["let-initializer build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests let_initializer -- --nocapture",
    }
}

fn for_loop_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/forall_loop.rs",
        sugar: "ForAllLoopSugar",
        role: "statement composite",
        claim: "for-loop forall composite claim",
        recognizer: "recognize bounded for-loop assertion bodies and capture domain/body children",
        desugar: "delegate finite domains to SequenceFloor and body formulas to ConstraintFloor, exact-or-bail",
        floors: &["SequenceFloor", "BoolFloor", "ConstraintFloor"],
        delete_from_lib: &["for-loop build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests forall_loop -- --nocapture",
    }
}

fn while_replay_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/for_replay.rs",
        sugar: "WhileReplaySugar",
        role: "statement composite",
        claim: "while-to-for replay composite claim",
        recognizer:
            "recognize replayable literal while loops and capture the synthesized for-loop body",
        desugar: "delegate the synthesized loop to ForAllLoopSugar through CompositeFloor",
        floors: &["CompositeFloor", "SequenceFloor", "ConstraintFloor"],
        delete_from_lib: &["while replay build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests for_replay -- --nocapture",
    }
}

fn conditional_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/conditional.rs",
        sugar: "ConditionalSugar",
        role: "statement composite",
        claim: "conditional composite claim",
        recognizer: "recognize if/else assertion bodies and capture guard plus branch composites",
        desugar: "delegate guard to BoolFloor and branch assertions to ConstraintFloor, emitting guarded implications",
        floors: &["BoolFloor", "CompositeFloor", "ConstraintFloor"],
        delete_from_lib: &["if build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests conditional -- --nocapture",
    }
}

fn match_composite_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/match_node.rs",
        sugar: "MatchSugar",
        role: "statement composite",
        claim: "match composite claim",
        recognizer: "recognize match assertion bodies and capture scrutinee/pattern/arm composites",
        desugar: "delegate scrutinee/pattern floors and emit guarded arm formulas through ConstraintFloor",
        floors: &["TermFloor", "CompositeFloor", "ConstraintFloor"],
        delete_from_lib: &["match build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests match_node -- --nocapture",
    }
}

fn statement_composite_plan() -> ReplacementPlan {
    ReplacementPlan {
        module: "src/sugar/statement_position.rs",
        sugar: "StatementCompositeSugar",
        role: "statement composite",
        claim: "statement-position composite claim",
        recognizer: "recognize bare expression statements claimed by fold/for_each/composite sugars",
        desugar: "delegate owned expression composites to CompositeFloor and leave callsite/non-composite routes alone",
        floors: &["CompositeFloor", "ConstraintFloor"],
        delete_from_lib: &["fallback statement build_composite call inside collect_assertion_entries"],
        focused_test: "cargo test -p sugar-lift-rust-tests statement_position -- --nocapture",
    }
}
