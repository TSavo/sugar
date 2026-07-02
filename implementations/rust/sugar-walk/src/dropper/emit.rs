// SPDX-License-Identifier: Apache-2.0

use super::gap::Gap;
use super::predicate::PredicateDescriptor;
use super::template::DropTemplate;

/// The result of splicing a drop template into a source string.
#[derive(Debug, Clone)]
pub struct EmitResult {
    /// The modified source text with the guard inserted.
    pub modified_source: String,
    /// The template that was applied.
    pub template: DropTemplate,
    /// The variable name the guard was applied to.
    pub var_name: String,
    /// The line number (1-indexed) where the guard was inserted.
    pub insert_line: usize,
}

/// Splice the chosen template into `source` for the given gap.
///
/// Insertion strategy is **AST-anchored**: parse the source, locate the caller
/// function by name, find the callsite statement by index, and splice the
/// rendered guard text immediately before that line.
///
/// Returns `None` if the source does not parse, the caller is absent, the
/// stmt_index is out of range, or the template is not renderable.
pub fn emit_drop(
    source: &str,
    gap: &Gap,
    template: DropTemplate,
    descriptor: &dyn PredicateDescriptor,
) -> Option<EmitResult> {
    use syn::spanned::Spanned;

    let guard_text = match descriptor.render(template, &gap.var_name) {
        Ok(text) => text,
        Err(_) => return None,
    };

    let file: syn::File = match syn::parse_str(source) {
        Ok(file) => file,
        Err(_) => return None,
    };

    let caller_fn = file.items.iter().find_map(|item| {
        if let syn::Item::Fn(f) = item {
            if f.sig.ident == gap.caller_name {
                return Some(f);
            }
        }
        None
    })?;

    let callsite_stmt = caller_fn.block.stmts.get(gap.callsite_stmt_index)?;

    let callsite_line_1indexed = callsite_stmt.span().start().line;
    if callsite_line_1indexed == 0 {
        return None;
    }
    let insert_before_idx = callsite_line_1indexed - 1;

    let lines: Vec<&str> = source.lines().collect();
    if insert_before_idx >= lines.len() {
        return None;
    }

    let guard_trimmed = guard_text.trim_end_matches('\n');
    let mut result_lines: Vec<&str> = Vec::with_capacity(lines.len() + 1);
    for (i, line) in lines.iter().enumerate() {
        if i == insert_before_idx {
            result_lines.push(guard_trimmed);
        }
        result_lines.push(line);
    }

    let modified_source = result_lines.join("\n");
    Some(EmitResult {
        modified_source,
        template,
        var_name: gap.var_name.clone(),
        insert_line: callsite_line_1indexed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dropper::gap::detect_gaps;
    use crate::dropper::predicates::not_null::NotNullPredicate;
    use crate::walk::walk_callsites_to_entry;
    use crate::wp::Wp;
    use sugar_ir_types::{IrFormula, IrTerm};

    fn not_null_wp(var_name: &str) -> Wp {
        Wp(IrFormula::Atomic {
            name: "not_null".to_string(),
            args: vec![IrTerm::Var {
                name: var_name.to_string(),
            }],
        })
    }

    const FIXTURE_SRC: &str = r#"
fn f(x: Option<i32>) -> i32 {
    x.unwrap()
}

fn caller(x: Option<i32>) {
    f(x);
}
"#;

    fn find_caller(src: &str, name: &str) -> syn::ItemFn {
        let file: syn::File = syn::parse_str(src).expect("parses");
        file.items
            .iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == name => Some(f.clone()),
                _ => None,
            })
            .expect("caller fn")
    }

    #[test]
    fn emit_drop_inserts_guard_before_callsite() {
        let caller_fn = find_caller(FIXTURE_SRC, "caller");
        let walks = walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], not_null_wp("x"));
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        let gap = &gaps[0];

        let result = emit_drop(FIXTURE_SRC, gap, DropTemplate::Defensive, &NotNullPredicate)
            .expect("emit succeeds");

        let guard_pos = result
            .modified_source
            .find("x.is_none()")
            .expect("guard present");
        let callsite_pos = result
            .modified_source
            .find("f(x)")
            .expect("callsite present");
        assert!(
            guard_pos < callsite_pos,
            "guard must appear before callsite: guard_pos={}, callsite_pos={}",
            guard_pos,
            callsite_pos
        );
    }

    #[test]
    fn emitted_source_is_syntactically_valid() {
        let caller_fn = find_caller(FIXTURE_SRC, "caller");
        let walks = walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], not_null_wp("x"));
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        let gap = &gaps[0];

        let result = emit_drop(FIXTURE_SRC, gap, DropTemplate::Defensive, &NotNullPredicate)
            .expect("emit succeeds");

        let parse_result: Result<syn::File, _> = syn::parse_str(&result.modified_source);
        assert!(
            parse_result.is_ok(),
            "emitted source must be syntactically valid Rust: {:?}",
            parse_result.err()
        );
    }

    #[test]
    fn emit_drop_routes_to_correct_caller_in_multi_function_file() {
        let src = "\
fn f(x: Option<i32>) -> i32 {
    x.unwrap()
}

fn caller_a(x: Option<i32>) {
    f(x);
}

fn caller_b(x: Option<i32>) {
    f(x);
}
";
        let caller_a = find_caller(src, "caller_a");
        let walks = walk_callsites_to_entry(&caller_a, "f", &["x".to_string()], not_null_wp("x"));
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        assert_eq!(gaps.len(), 1, "one gap in caller_a");
        let gap = &gaps[0];
        assert_eq!(gap.caller_name, "caller_a");

        let result =
            emit_drop(src, gap, DropTemplate::Defensive, &NotNullPredicate).expect("emit succeeds");

        let modified = &result.modified_source;
        let caller_a_pos = modified.find("fn caller_a").expect("caller_a present");
        let caller_b_pos = modified.find("fn caller_b").expect("caller_b present");
        let guard_pos = modified.find("x.is_none()").expect("guard present");
        assert!(
            caller_a_pos < guard_pos && guard_pos < caller_b_pos,
            "guard must land between caller_a and caller_b. \
             caller_a@{}, guard@{}, caller_b@{}\nmodified:\n{}",
            caller_a_pos,
            guard_pos,
            caller_b_pos,
            modified
        );
        syn::parse_str::<syn::File>(modified).expect("modified source parses");
    }

    #[test]
    fn emit_drop_routes_to_correct_callsite_in_multi_callsite_function() {
        let src = "\
fn f(x: Option<i32>) -> i32 {
    x.unwrap()
}

fn caller(x: Option<i32>) {
    f(x);
    let y = x;
    f(y);
}
";
        let caller_fn = find_caller(src, "caller");
        let walks = walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], not_null_wp("x"));
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        assert!(gaps.len() >= 2, "two callsites yield two gaps");
        let second_gap = gaps
            .iter()
            .find(|g| g.callsite_stmt_index == 2)
            .expect("gap at stmt_index 2 (second f call)");

        let result = emit_drop(src, second_gap, DropTemplate::Defensive, &NotNullPredicate)
            .expect("emit succeeds");
        let modified = &result.modified_source;

        let first_call_pos = modified.find("f(x);").expect("first call f(x) present");
        let let_y_pos = modified.find("let y").expect("let y present");
        let second_call_pos = modified.find("f(y);").expect("second call f(y) present");
        let guard_pos = modified.find("is_none()").expect("guard present");

        assert!(
            first_call_pos < let_y_pos,
            "first callsite must precede let-binding"
        );
        assert!(
            let_y_pos < guard_pos,
            "guard must follow let-binding (not precede first callsite)"
        );
        assert!(
            guard_pos < second_call_pos,
            "guard must precede second callsite"
        );

        syn::parse_str::<syn::File>(modified).expect("modified source parses");
    }
}
