//! Dissolving rust stdlib sugar by throwing it at the compiler.
//!
//! THE STDLIB-SUGAR HANDLER (T 2026-06-14). This is NOT a catch/fallback for things
//! symbolic lifting failed on. It is the first-class, designated handler for ONE
//! category: rust *standard-library sugar* -- the closed, deterministic, total,
//! effect-free computations that are "just how rust is written" (float formatting,
//! char case-mapping, `escape_*`, ...). We deliberately do NOT model these in FOL,
//! because stdlib IS the axiom: a stdlib term is dissolved by EVALUATING it with the
//! same stdlib the kit ships. "Need stdlib to prove stdlib? Yes -- that's the named,
//! pinned TCB; axioms all the way down, then a floor with a name on it." User logic
//! is still modeled and checked; only stdlib sugar is dissolved this way.
//!
//! THE TRICK (T): we already have the compiling code. Don't reconstruct a minimal
//! snippet by hand -- lift the problematic stdlib term (and any *pure local helpers*
//! it calls) verbatim into a throwaway harness, hand it to `rustc`, and run it. The
//! harness CONTAINS stdlib, so stdlib is its own evaluation table -- nothing
//! hand-mapped, nothing to drift. A green run is the dissolution; it is sound because
//! the term is closed + deterministic (so one run is universal) and the toolchain is
//! pinned (so the answer is reproducible / re-walkable).
//!
//! THE HARD BOUNDARY (T, emphatic): this is ONLY for vendor-written STDLIB SUGAR. It
//! is NOT a general "we couldn't model this expression, so let's just run it" cheat.
//! Running an expression to trust its result is the green-tests trap / the EUF
//! tautology in another coat: it trusts the code-under-test. The dividing line is what
//! the vendor WROTE:
//!   * vendor wrote stdlib sugar (`format!`, `.to_lowercase()`, `.count_ones()`) ->
//!     DISSOLVE (stdlib is the axiom; evaluating it grounds in the named TCB).
//!   * vendor wrote logic we are meant to verify -> MODEL + CHECK it; never run-to-trust.
//! A USER function NEVER qualifies, even if closed and pure -- the user's algorithm is
//! precisely the thing under proof; harnessing it would be circular. The eligibility
//! GATE is therefore an ALLOWLIST of stdlib's own pure surface (a carried local helper
//! qualifies only if its body bottoms out, recursively, in stdlib sugar + literals --
//! no user algorithm). This driver must NEVER be invoked on anything the gate has not
//! certified as stdlib sugar.
//!
//! THIRD FENCE -- UNIT-TEST ASSERTIONS ONLY, NEVER GENERALIZATION (T). This applies
//! solely to detected unit-test assertions: a finite set of pinned CONCRETE
//! `(input -> output)` instances. Each is closed, so each is evaluable, and one run is
//! the WHOLE truth for that instance. A GENERALIZATION (`forall x. P(x)`, a free
//! variable) cannot be run -- a single concrete run is only a sample, never a proof of
//! the universal -- so dissolution may NEVER touch it. We discharge exactly the
//! concrete assertion the vendor pinned and never extrapolate to a general property.
//! ("Vendor tests ARE the spec": lift the concrete claim, do not invent a universal.)
//! The gate folds all three fences into one predicate: CLOSED (no free vars) =
//! concrete = unit-test-shaped; a free var (generalization) disqualifies, exactly as a
//! non-stdlib op (user logic) disqualifies.
//!
//! SOUNDNESS BOUNDARY (ours, not stdlib's): the gate decides eligibility; the harness
//! only supplies VALUES. This module is just the driver: given a prelude + a list of
//! gated stdlib-sugar assert statements, compile once, run, and report which held.

use std::io::Write;
use std::path::Path;
use std::process::Command;

use syn::Expr;

/// Method/function names that are NOT value-sugar: pointer/address, time, IO, RNG,
/// concurrency, env/fs, unsafe reinterpretation. An assertion operand naming any of
/// these is rejected (out of the stdlib-VALUE-sugar category, per T's boundaries) even
/// if it happens to evaluate deterministically. Closedness (below) already rejects the
/// common cases (their receivers are runtime locals, not literals); this is a focused
/// backstop for the rare impure-op-on-a-literal.
const IMPURE_NAMES: &[&str] = &[
    "as_ptr", "as_mut_ptr", "addr", "expose_addr", "expose_provenance", "with_addr",
    "from_raw", "into_raw", "transmute", "transmute_copy", "assume_init",
    "now", "elapsed", "duration_since", "instant",
    "read", "write", "read_to_string", "stdin", "stdout", "stderr", "lock",
    "random", "gen", "gen_range", "fill", "next_u32", "next_u64",
    "spawn", "join", "load", "store", "fetch_add", "fetch_sub", "fetch_or",
    "compare_exchange", "swap", "send", "recv", "try_recv",
    "var", "vars", "args", "open", "metadata", "create", "remove_file",
];

/// Certify that every operand of a unit-test assertion is CLOSED STDLIB VALUE SUGAR
/// (fences #1-#3): built only from literals / const-or-ctor paths and stdlib method
/// calls, with NO free variable (generalization), NO call to a user/local function
/// (logic to model), and NO impure op. This is the eligibility gate; only operands it
/// certifies may be handed to the harness driver.
pub fn assert_operands_are_stdlib_sugar(operands: &[&Expr]) -> bool {
    !operands.is_empty() && operands.iter().all(|e| closed_pure_sugar(e))
}

/// A path is an acceptable closed leaf if it is a value constructor / enum variant
/// (`Some`/`Ok`/`Err`/`Ordering::Less`/...) or a SCREAMING_SNAKE associated const
/// (`f64::MAX`, `char::MAX`, `u32::BITS`). A bare lowercase identifier is a free
/// variable or a local binding -> rejected (not closed).
fn is_const_or_ctor_path(p: &syn::Path) -> bool {
    let Some(last) = p.path_last_ident() else {
        return false;
    };
    let s = last;
    // value ctors / enum variants: first char uppercase, rest not screaming-only is fine
    let first_upper = s.chars().next().map(|c| c.is_uppercase()).unwrap_or(false);
    // SCREAMING_SNAKE const: all uppercase / digits / underscore
    let screaming = !s.is_empty()
        && s.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_');
    first_upper || screaming
}

trait PathLastIdent {
    fn path_last_ident(&self) -> Option<String>;
}
impl PathLastIdent for syn::Path {
    fn path_last_ident(&self) -> Option<String> {
        self.segments.last().map(|s| s.ident.to_string())
    }
}

fn closed_pure_sugar(expr: &Expr) -> bool {
    match expr {
        // literals: the pinned leaves.
        Expr::Lit(_) => true,
        // const / ctor / variant path (None, f64::MAX, Ordering::Less); a bare lowercase
        // ident (free var / local) fails is_const_or_ctor_path.
        Expr::Path(p) => is_const_or_ctor_path(&p.path),
        // value constructor / variant call: Some(x), Ok(x), Wrapping(x). The callee must
        // be an uppercase ctor path (NOT a lowercase user/local fn -> fence #1), args pure.
        Expr::Call(c) => {
            let ctor = matches!(c.func.as_ref(), Expr::Path(p) if is_const_or_ctor_path(&p.path));
            ctor && c.args.iter().all(closed_pure_sugar)
        }
        // stdlib method sugar on a closed receiver: 'A'.to_digit(16), "x".to_ascii_uppercase().
        // Receiver + args must be closed-pure; the method name must not be impure.
        Expr::MethodCall(m) => {
            let name = m.method.to_string();
            !IMPURE_NAMES.contains(&name.as_str())
                && closed_pure_sugar(&m.receiver)
                && m.args.iter().all(closed_pure_sugar)
        }
        // format!/concat!/... over pure args is value sugar; reject impure-named macros.
        Expr::Macro(mac) => {
            use syn::parse::Parser;
            use syn::punctuated::Punctuated;
            let name = mac
                .mac
                .path
                .path_last_ident()
                .unwrap_or_default();
            if !matches!(name.as_str(), "format" | "concat" | "stringify" | "vec") {
                return false;
            }
            let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            match parser.parse2(mac.mac.tokens.clone()) {
                // stringify! takes arbitrary tokens but its result is a literal of the
                // SOURCE text -- pure regardless of args.
                _ if name == "stringify" => true,
                Ok(args) => args.iter().all(closed_pure_sugar),
                Err(_) => false,
            }
        }
        Expr::Unary(u) => closed_pure_sugar(&u.expr),
        Expr::Binary(b) => closed_pure_sugar(&b.left) && closed_pure_sugar(&b.right),
        Expr::Paren(p) => closed_pure_sugar(&p.expr),
        Expr::Group(g) => closed_pure_sugar(&g.expr),
        Expr::Reference(r) => closed_pure_sugar(&r.expr),
        Expr::Array(a) => a.elems.iter().all(closed_pure_sugar),
        Expr::Tuple(t) => t.elems.iter().all(closed_pure_sugar),
        Expr::Cast(c) => closed_pure_sugar(&c.expr),
        Expr::Index(i) => closed_pure_sugar(&i.expr) && closed_pure_sugar(&i.index),
        // everything else (Field, If, Block, Closure, Await, bare local Call, ...) is
        // not certified -> the assertion stays unclassified (safe under-claim).
        _ => false,
    }
}

/// True if any operand subtree performs a stdlib SUGAR operation (a method call or a
/// `format!`/`concat!` macro) -- the operations the symbolic lifter cannot model and
/// therefore leaves unclassified. Requiring this avoids double-counting: a dissolvable
/// candidate is exactly an assert the lifter could not discharge on its own.
fn operands_use_stdlib_op(operands: &[&Expr]) -> bool {
    struct W {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for W {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            self.found = true;
            syn::visit::visit_expr_method_call(self, m);
        }
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            if let Some(seg) = m.path.segments.last() {
                let n = seg.ident.to_string();
                if matches!(n.as_str(), "format" | "concat") {
                    self.found = true;
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = W { found: false };
    for e in operands {
        syn::visit::Visit::visit_expr(&mut w, e);
    }
    w.found
}

/// Walk a file for unit-test assertions that are CLOSED STDLIB VALUE SUGAR (gate) and
/// perform at least one stdlib sugar op the symbolic lifter cannot model. Returns each
/// as a reconstructed, message-stripped assert statement (`assert_eq!(LHS, RHS)` /
/// `assert!(COND)`) ready to drop into a harness. Message args are dropped so a message
/// referencing a runtime local cannot break the harness compile.
pub fn collect_dissolvable_asserts(file: &syn::File) -> Vec<String> {
    use syn::parse::Parser;
    use syn::punctuated::Punctuated;
    struct W {
        out: Vec<String>,
    }
    impl<'ast> syn::visit::Visit<'ast> for W {
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            let name = m
                .path
                .segments
                .last()
                .map(|s| s.ident.to_string())
                .unwrap_or_default();
            let kind = match name.as_str() {
                "assert_eq" | "debug_assert_eq" => Some("assert_eq"),
                "assert_ne" | "debug_assert_ne" => Some("assert_ne"),
                "assert" | "debug_assert" => Some("assert"),
                _ => None,
            };
            if let Some(macro_name) = kind {
                let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
                if let Ok(args) = parser.parse2(m.tokens.clone()) {
                    let ops: Vec<&Expr> = args.iter().collect();
                    let value_ops: Vec<&Expr> = if macro_name == "assert" {
                        ops.iter().take(1).copied().collect()
                    } else {
                        ops.iter().take(2).copied().collect()
                    };
                    let enough = if macro_name == "assert" {
                        value_ops.len() == 1
                    } else {
                        value_ops.len() == 2
                    };
                    if enough
                        && assert_operands_are_stdlib_sugar(&value_ops)
                        && operands_use_stdlib_op(&value_ops)
                    {
                        let stmt = if macro_name == "assert" {
                            format!("assert!({})", quote::quote!(#(#value_ops)*))
                        } else {
                            let l = value_ops[0];
                            let r = value_ops[1];
                            format!("{}!({}, {})", macro_name, quote::quote!(#l), quote::quote!(#r))
                        };
                        self.out.push(stmt);
                    }
                }
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = W { out: Vec::new() };
    syn::visit::Visit::visit_file(&mut w, file);
    w.out
}

/// Outcome of a harness compile+run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HarnessResult {
    /// The harness compiled and ran; per-assert (by index) whether it held.
    Ran(Vec<bool>),
    /// The harness did not compile -- nothing is dissolved (safe: the asserts stay
    /// unclassified). Carries rustc's stderr (truncated) for diagnostics.
    CompileError(String),
    /// The two determinism runs disagreed -- the term was not deterministic after all,
    /// so NONE of its asserts may be dissolved (every index forced to `false`).
    Nondeterministic,
    /// rustc / the binary could not be invoked (toolchain absent). Caller treats this
    /// like CompileError: dissolve nothing.
    Unavailable(String),
}

/// Compile a harness of `prelude` (imports + pure local helper defs) plus a `main`
/// that runs each statement in `asserts`, printing `OK <i>` iff statement `i` does NOT
/// panic (caught per-assert via `catch_unwind`). Runs TWICE under `rustc` and requires
/// identical results (determinism sanity). `rustc` is the toolchain invocation (e.g.
/// `"rustc"`, or a `rustup run <toolchain> rustc` split handled by the caller via
/// `rustc_args`). `work_dir` must exist and be writable.
pub fn evaluate_asserts(
    prelude: &str,
    asserts: &[String],
    rustc: &str,
    rustc_args: &[String],
    edition: &str,
    work_dir: &Path,
) -> HarnessResult {
    if asserts.is_empty() {
        return HarnessResult::Ran(Vec::new());
    }
    let src = build_harness_source(prelude, asserts);
    let src_path = work_dir.join("sugar_closed_eval_probe.rs");
    let bin_path = work_dir.join("sugar_closed_eval_probe_bin");
    if let Err(e) = std::fs::File::create(&src_path).and_then(|mut f| f.write_all(src.as_bytes())) {
        return HarnessResult::Unavailable(format!("write harness: {e}"));
    }

    // Compile.
    let mut cmd = Command::new(rustc);
    cmd.args(rustc_args)
        .arg("--edition")
        .arg(edition)
        .arg("-A")
        .arg("warnings")
        .arg(&src_path)
        .arg("-o")
        .arg(&bin_path);
    let compile = match cmd.output() {
        Ok(o) => o,
        Err(e) => return HarnessResult::Unavailable(format!("invoke rustc: {e}")),
    };
    if !compile.status.success() {
        let mut err = String::from_utf8_lossy(&compile.stderr).to_string();
        err.truncate(2000);
        return HarnessResult::CompileError(err);
    }

    // Run twice for determinism.
    let run1 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    let run2 = match run_and_collect(&bin_path, asserts.len()) {
        Ok(v) => v,
        Err(e) => return HarnessResult::Unavailable(e),
    };
    if run1 != run2 {
        return HarnessResult::Nondeterministic;
    }
    HarnessResult::Ran(run1)
}

/// Build the harness: prelude, then a `main` that runs each assert under a silenced
/// panic hook and prints `OK <i>` for each that does not panic.
fn build_harness_source(prelude: &str, asserts: &[String]) -> String {
    let mut s = String::new();
    s.push_str(prelude);
    s.push_str("\n#[allow(unused)]\nfn main() {\n");
    // Silence panic output so a deliberately-failing assert does not spam stderr.
    s.push_str("    std::panic::set_hook(Box::new(|_| {}));\n");
    for (i, a) in asserts.iter().enumerate() {
        // Each assert is wrapped so a panic is caught and only the survivors print OK.
        let stmt = a.trim().trim_end_matches(';');
        s.push_str(&format!(
            "    if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {{ {stmt}; }})).is_ok() {{ println!(\"OK {i}\"); }}\n"
        ));
    }
    s.push_str("}\n");
    s
}

fn run_and_collect(bin: &Path, n: usize) -> Result<Vec<bool>, String> {
    let out = Command::new(bin)
        .output()
        .map_err(|e| format!("run harness: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut held = vec![false; n];
    for line in stdout.lines() {
        if let Some(rest) = line.strip_prefix("OK ") {
            if let Ok(i) = rest.trim().parse::<usize>() {
                if i < n {
                    held[i] = true;
                }
            }
        }
    }
    Ok(held)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rustc_available() -> bool {
        Command::new("rustc")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    fn gate(src: &str) -> bool {
        let e: Expr = syn::parse_str(src).expect("parse");
        assert_operands_are_stdlib_sugar(&[&e])
    }

    #[test]
    fn gate_accepts_closed_stdlib_value_sugar() {
        // direct stdlib method sugar on literals
        assert!(gate("'0'.to_digit(10)"));
        assert!(gate("'A'.to_digit(16)"));
        assert!(gate(r#""url()URL()".to_ascii_uppercase()"#));
        assert!(gate("'A'.to_lowercase().collect::<String>()"));
        // value ctors / variants as RHS expecteds
        assert!(gate("Some(10)"));
        assert!(gate("None"));
        // consts
        assert!(gate("f64::MAX"));
        assert!(gate("u32::BITS"));
        // format! sugar over literals
        assert!(gate(r#"format!("{}", 3.14_f64)"#));
        // literals, refs, byte
        assert!(gate("b'0'"));
        assert!(gate(r#""HİKß""#));
        // arithmetic over literals
        assert!(gate("1.0 / 0.0"));
    }

    #[test]
    fn gate_rejects_non_sugar_the_fences() {
        // FENCE #3 generalization: a free variable (param/local) is not closed.
        assert!(!gate("c"));
        assert!(!gate("c.to_lowercase().collect::<String>()"));
        // FENCE #1 user/local function call (lowercase callee) -> model it, don't run it.
        assert!(!gate("lower('A')"));
        assert!(!gate("my_helper(3, 4)"));
        // impure ops (pointer / time / IO / atomic), even on literals.
        assert!(!gate("'a'.encode_utf8(&mut buf).as_ptr()")); // free `buf` AND as_ptr
        assert!(!gate("Instant::now()")); // ctor-ish path but `now` is impure-named... it's a method-free call
        // field access / arbitrary expr -> not certified.
        assert!(!gate("x.field"));
        assert!(!gate("{ let y = 3; y }"));
    }

    #[test]
    fn harness_dissolves_true_and_refutes_false() {
        // Skip when the toolchain is absent (CI hosts without rustc) -- never fail
        // for an environment reason.
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness driver test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test");
        let _ = std::fs::create_dir_all(&dir);
        let asserts = vec![
            // closed stdlib sugar: true
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "a")"#.to_string(),
            // closed stdlib sugar: false (break-the-twin -- must NOT be reported held)
            r#"assert_eq!('A'.to_lowercase().collect::<String>(), "z")"#.to_string(),
            // another true
            r#"assert_eq!(format!("{}", 3.14_f64), "3.14")"#.to_string(),
        ];
        let res = evaluate_asserts("", &asserts, "rustc", &[], "2021", &dir);
        match res {
            HarnessResult::Ran(held) => {
                assert_eq!(held, vec![true, false, true], "true/false/true expected");
            }
            other => panic!("expected Ran, got {other:?}"),
        }
    }

    #[test]
    fn harness_carries_a_pure_local_helper() {
        if !rustc_available() {
            eprintln!("rustc unavailable; skipping harness helper test");
            return;
        }
        let dir = std::env::temp_dir().join("sugar_closed_eval_test_helper");
        let _ = std::fs::create_dir_all(&dir);
        let prelude = r#"
fn lower(c: char) -> String {
    let to_lowercase = c.to_lowercase();
    assert_eq!(to_lowercase.len(), to_lowercase.count());
    c.to_lowercase().collect()
}
"#;
        let asserts = vec![
            r#"assert_eq!(lower('A'), "a")"#.to_string(),
            r#"assert_eq!(lower('Σ'), "σ")"#.to_string(),
        ];
        match evaluate_asserts(prelude, &asserts, "rustc", &[], "2021", &dir) {
            HarnessResult::Ran(held) => assert_eq!(held, vec![true, true]),
            other => panic!("expected Ran, got {other:?}"),
        }
    }
}
