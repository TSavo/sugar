//! A correctness-first declarative macro expander for the assertion lifter.
//!
//! The lifter desugars a language using the language: `a(x)` desugars to `a(x)`,
//! then we walk into the definition of `a`. For a `macro_rules!` macro, walking
//! into the definition means expanding it. This module performs that expansion
//! for the matcher shapes it can match EXACTLY, and refuses (returns
//! `Err(reason)`) for anything it cannot match. It never guesses an expansion:
//! a wrong expansion would be a false-pass, so unsupported matcher grammar is a
//! named refusal, not a silent or approximate result.
//!
//! Supported matcher grammar (the common assertion-macro shapes):
//!   - literal tokens (idents, puncts, literals, nested delimiter groups)
//!   - single-fragment metavariables: `$x:expr|ty|ident|literal|tt|pat|path|block`
//!   - one optional group: `$( ... )?`
//!   - one repetition group: `$( ... )sep*` / `$( ... )sep+` (separator optional)
//! Nested repetitions, `::+`-style segment repetition, and other advanced
//! grammar return `Err` so the caller refuses by name.

use std::collections::BTreeMap;

use proc_macro2::{Delimiter, Spacing, TokenStream, TokenTree};

/// One declarative macro rule: either `(matcher) => { body }` (`macro_rules!`
/// and rule-list `pub macro`) or `(matcher) { body }` (single-rule `pub macro`).
pub(crate) struct MacroRule {
    matcher: Vec<TokenTree>,
    body: TokenStream,
}

/// A captured metavariable binding.
#[derive(Clone)]
enum Binding {
    /// A single fragment capture: the tokens bound to `$x`.
    Single { tokens: TokenStream, frag: String },
    /// A repetition capture: one set of inner bindings per repetition round.
    Repeated(Vec<Bindings>),
}

type Bindings = BTreeMap<String, Binding>;

/// Parse the token stream of a declarative macro body into its rules.
/// The grammar is `(matcher) => { body } ;` repeated for `macro_rules!` and
/// rule-list `pub macro`, or `(matcher) { body }` for single-rule `pub macro`.
/// Returns `Err` if the shape is not recognized so the caller refuses rather
/// than mis-parses.
pub(crate) fn parse_rules(tokens: TokenStream) -> Result<Vec<MacroRule>, String> {
    let trees: Vec<TokenTree> = tokens.into_iter().collect();
    let mut rules = Vec::new();
    let mut i = 0;
    while i < trees.len() {
        // matcher group
        let matcher = match &trees[i] {
            TokenTree::Group(g) => g.stream().into_iter().collect::<Vec<_>>(),
            other => return Err(format!("macro_rules: expected matcher group, got {other}")),
        };
        i += 1;
        // `=>` for macro_rules / rule-list `pub macro`, or directly a body
        // group for single-rule `pub macro name($matcher) { body }`.
        let arrow_ok = matches!(trees.get(i), Some(TokenTree::Punct(p)) if p.as_char() == '=' && p.spacing() == Spacing::Joint)
            && matches!(trees.get(i + 1), Some(TokenTree::Punct(p)) if p.as_char() == '>');
        if arrow_ok {
            i += 2;
        }
        // body group
        let body = match trees.get(i) {
            Some(TokenTree::Group(g)) => g.stream(),
            other if arrow_ok => {
                return Err(format!("macro_rules: expected body group, got {other:?}"));
            }
            other => {
                return Err(format!(
                    "declarative macro: expected `=>` or body group after matcher, got {other:?}"
                ));
            }
        };
        i += 1;
        rules.push(MacroRule { matcher, body });
        // optional rule separator: `macro_rules!` normally uses `;`, while
        // `pub macro` rule lists use `,`.
        if matches!(trees.get(i), Some(TokenTree::Punct(p)) if p.as_char() == ';' || p.as_char() == ',')
        {
            i += 1;
        }
    }
    if rules.is_empty() {
        return Err("macro_rules: no rules parsed".to_string());
    }
    Ok(rules)
}

/// A stable textual signature of a rule set, used to tell whether two scanned
/// definitions of the same macro name are the same definition (the crate seen
/// twice) or genuinely conflicting (ambiguous).
pub(crate) fn rules_signature(rules: &[MacroRule]) -> String {
    rules
        .iter()
        .map(|r| {
            let matcher: String = r
                .matcher
                .iter()
                .map(|t| t.to_string())
                .collect::<Vec<_>>()
                .join(" ");
            format!("{matcher} => {{ {} }}", r.body)
        })
        .collect::<Vec<_>>()
        .join(" ; ")
}

/// Expand an invocation `input` against a macro's rules. Tries each rule in
/// order; the first whose matcher matches the entire input is transcribed.
/// Returns `Err` if no rule matches or the matched rule uses grammar the
/// transcriber does not support.
pub(crate) fn expand(rules: &[MacroRule], input: TokenStream) -> Result<TokenStream, String> {
    let input_trees: Vec<TokenTree> = input.into_iter().collect();
    for rule in rules {
        if let Some(bindings) = match_seq(&rule.matcher, &input_trees) {
            return transcribe(rule.body.clone(), &bindings);
        }
    }
    Err("macro expansion: no rule matched the invocation".to_string())
}

/// Match a matcher token sequence against the full input sequence. Returns the
/// captured bindings only on a complete match (matcher and input both consumed).
fn match_seq(matcher: &[TokenTree], input: &[TokenTree]) -> Option<Bindings> {
    let mut bindings = Bindings::new();
    let consumed = match_prefix(matcher, input, &mut bindings, None)?;
    if consumed == input.len() {
        Some(bindings)
    } else {
        None
    }
}

/// Try to match `matcher` against a prefix of `input`, recording bindings.
/// Returns the number of input token-trees consumed, or `None` on mismatch /
/// unsupported grammar.
fn match_prefix(
    matcher: &[TokenTree],
    input: &[TokenTree],
    bindings: &mut Bindings,
    terminator: Option<&TokenTree>,
) -> Option<usize> {
    let mut mi = 0;
    let mut ii = 0;
    while mi < matcher.len() {
        match &matcher[mi] {
            // Metavariable or repetition: `$`
            TokenTree::Punct(p) if p.as_char() == '$' => {
                match matcher.get(mi + 1) {
                    // `$( ... )...` repetition or optional group
                    Some(TokenTree::Group(g)) if g.delimiter() == Delimiter::Parenthesis => {
                        let inner: Vec<TokenTree> = g.stream().into_iter().collect();
                        // separator and repeat operator follow the group
                        let (sep, op, advance) = parse_rep_suffix(&matcher[mi + 2..])?;
                        let follow = &matcher[mi + 2 + advance..];
                        let consumed =
                            match_repetition(&inner, sep, op, follow, &input[ii..], bindings)?;
                        ii += consumed;
                        mi += 2 + advance;
                    }
                    // `$name:frag` metavariable
                    Some(TokenTree::Ident(name)) => {
                        // expect `:` then fragment specifier ident
                        let colon_ok = matches!(matcher.get(mi + 2), Some(TokenTree::Punct(p)) if p.as_char() == ':');
                        let frag = match matcher.get(mi + 3) {
                            Some(TokenTree::Ident(f)) if colon_ok => f.to_string(),
                            _ => return None, // unsupported: `$name` without fragment spec
                        };
                        // Follow token for a greedy fragment: the next matcher
                        // token. If that next token opens a `$( .. )` group (an
                        // optional / repetition that may be absent), the real
                        // follow is the group's first inner token (its separator,
                        // e.g. the `,` in `$r:expr $(, ..)?`), not `$`; otherwise
                        // the fragment would greedily swallow the rest. Fall back
                        // to the caller's terminator when this metavar ends the
                        // matcher.
                        let follow = match matcher.get(mi + 4) {
                            Some(TokenTree::Punct(p))
                                if p.as_char() == '$'
                                    && matches!(matcher.get(mi + 5), Some(TokenTree::Group(g)) if g.delimiter() == Delimiter::Parenthesis) =>
                            {
                                match matcher.get(mi + 5) {
                                    Some(TokenTree::Group(g)) => {
                                        // Use the group's first inner token as the
                                        // boundary (works even if the group repeats).
                                        // Stored to extend its lifetime for the match.
                                        group_first_token(g).or(terminator.cloned())
                                    }
                                    _ => terminator.cloned(),
                                }
                            }
                            Some(other) => Some(other.clone()),
                            None => terminator.cloned(),
                        };
                        let (captured, consumed) =
                            capture_fragment(&frag, &input[ii..], follow.as_ref())?;
                        bindings.insert(
                            name.to_string(),
                            Binding::Single {
                                tokens: captured,
                                frag,
                            },
                        );
                        ii += consumed;
                        mi += 4;
                    }
                    _ => return None,
                }
            }
            // A delimiter group that itself contains metavariables (e.g. the
            // `($valid:expr, $invalid:expr)` matcher group). The structural
            // `token_tree_eq` below would compare the matcher group's stream
            // (which holds `$valid : expr ...`) against the input group's
            // stream token-for-token and fail on length. Instead, recurse into
            // BOTH streams to bind the inner metavars. The delimiter must match,
            // and the inner matcher must consume the input group's ENTIRE stream
            // (a delimiter group is a closed boundary in rust's matcher, exactly
            // like the top-level `match_seq`) -- a partial consume is a mismatch.
            TokenTree::Group(mg) if matcher_group_has_metavar(mg) => {
                let inp = input.get(ii)?;
                let TokenTree::Group(ig) = inp else {
                    return None;
                };
                if mg.delimiter() != ig.delimiter() {
                    return None;
                }
                let inner_matcher: Vec<TokenTree> = mg.stream().into_iter().collect();
                let inner_input: Vec<TokenTree> = ig.stream().into_iter().collect();
                let consumed = match_prefix(&inner_matcher, &inner_input, bindings, None)?;
                if consumed != inner_input.len() {
                    return None;
                }
                ii += 1;
                mi += 1;
            }
            // Literal matcher token: must equal the next input token-tree.
            m => {
                let inp = input.get(ii)?;
                if !token_tree_eq(m, inp) {
                    return None;
                }
                ii += 1;
                mi += 1;
            }
        }
    }
    Some(ii)
}

/// The first token tree inside a group (its leading separator/literal), owned so
/// it can serve as a fragment-capture boundary for a metavar followed by a
/// `$( .. )` group.
fn group_first_token(g: &proc_macro2::Group) -> Option<TokenTree> {
    g.stream().into_iter().next()
}

/// Does a matcher delimiter group contain a metavariable / repetition (`$`)?
/// Only such groups need the recursive bind path; a purely-literal matcher
/// group (e.g. `()` in `foo()`) must still match by exact `token_tree_eq` so we
/// never over-match a literal-shaped group. The scan recurses into nested
/// groups so a `$` buried inside (`(($x))`) is still found.
fn matcher_group_has_metavar(g: &proc_macro2::Group) -> bool {
    g.stream().into_iter().any(|t| match t {
        TokenTree::Punct(p) => p.as_char() == '$',
        TokenTree::Group(inner) => matcher_group_has_metavar(&inner),
        _ => false,
    })
}

/// Parse the `sep? (*|+|?)` suffix that follows a `$( ... )` group.
/// Returns (separator token, operator char, number of matcher tokens consumed).
fn parse_rep_suffix(rest: &[TokenTree]) -> Option<(Option<TokenTree>, char, usize)> {
    match rest.first() {
        Some(TokenTree::Punct(p)) if matches!(p.as_char(), '*' | '+' | '?') => {
            Some((None, p.as_char(), 1))
        }
        // a separator token then the operator
        Some(sep) => match rest.get(1) {
            Some(TokenTree::Punct(p)) if matches!(p.as_char(), '*' | '+' | '?') => {
                Some((Some(sep.clone()), p.as_char(), 2))
            }
            _ => None,
        },
        None => None,
    }
}

/// Match a repetition group against input, stopping when the `follow` tokens
/// would match or input is exhausted. Records repeated inner bindings.
fn match_repetition(
    inner: &[TokenTree],
    sep: Option<TokenTree>,
    op: char,
    follow: &[TokenTree],
    input: &[TokenTree],
    bindings: &mut Bindings,
) -> Option<usize> {
    let mut ii = 0;
    let mut rounds: Vec<Bindings> = Vec::new();
    loop {
        // For `?` at most one round; stop if we already did one.
        if op == '?' && !rounds.is_empty() {
            break;
        }
        // If the follow tokens match here, stop the repetition.
        if !follow.is_empty() && follow_matches(follow, &input[ii..]) {
            break;
        }
        if ii >= input.len() {
            break;
        }
        // Expect a separator before all but the first round. Remember where the
        // separator started so we can BACKTRACK it: a separator is matched only
        // BETWEEN elements, so a TRAILING separator (`("a",..), ("b",..),` with a
        // dangling `,`) must be left unconsumed for a following matcher token
        // (e.g. the optional `$(,)?` trailing-comma group). Consuming it here and
        // then failing the next round -- which has no input left -- would fail
        // the whole match, the `assert_chunks!(.., (..), (..),)` corpus shape.
        let before_sep = ii;
        if let (Some(sep_tok), false) = (&sep, rounds.is_empty()) {
            match input.get(ii) {
                Some(t) if token_tree_eq(sep_tok, t) => ii += 1,
                _ => break,
            }
        }
        let mut round = Bindings::new();
        // Inside a round, a trailing greedy fragment must stop at the separator
        // (if any) or at the repetition's follow token.
        let round_terminator = sep.as_ref().or_else(|| follow.first());
        // `$($N:expr)+` has no separator and no follow token; the Rust matcher
        // still splits `0 1 2` into one expression fragment per round. Our
        // ordinary expr capture is intentionally greedy, so add the narrow,
        // unambiguous case here: one metavariable expression whose next token-tree
        // alone parses as an Expr. Anything composite/ambiguous declines.
        let matched = if sep.is_none() && round_terminator.is_none() {
            match_unseparated_single_expr_round(inner, &input[ii..], &mut round)
                .or_else(|| match_prefix(inner, &input[ii..], &mut round, round_terminator))
        } else {
            match_prefix(inner, &input[ii..], &mut round, round_terminator)
        };
        // A round that does not match (no input, or the inner matcher declines)
        // must NOT abort the whole repetition: backtrack any just-consumed
        // separator and stop cleanly. `?` short-circuits the `?`-operator
        // propagation that previously failed the match on a trailing separator.
        match matched {
            Some(consumed) if consumed > 0 => {
                ii += consumed;
                rounds.push(round);
            }
            _ => {
                ii = before_sep;
                break;
            }
        }
    }
    if op == '+' && rounds.is_empty() {
        return None;
    }
    // Merge: each metavar named in `inner` becomes a Repeated binding.
    for name in metavar_names(inner) {
        let collected = rounds
            .iter()
            .map(|r| {
                let mut m = Bindings::new();
                if let Some(b) = r.get(&name) {
                    m.insert(name.clone(), b.clone());
                }
                m
            })
            .collect();
        bindings.insert(name, Binding::Repeated(collected));
    }
    Some(ii)
}

fn match_unseparated_single_expr_round(
    inner: &[TokenTree],
    input: &[TokenTree],
    bindings: &mut Bindings,
) -> Option<usize> {
    if inner.len() != 4 {
        return None;
    }
    let TokenTree::Punct(dollar) = &inner[0] else {
        return None;
    };
    if dollar.as_char() != '$' {
        return None;
    }
    let TokenTree::Ident(name) = &inner[1] else {
        return None;
    };
    let TokenTree::Punct(colon) = &inner[2] else {
        return None;
    };
    if colon.as_char() != ':' {
        return None;
    }
    let TokenTree::Ident(frag) = &inner[3] else {
        return None;
    };
    if frag != "expr" {
        return None;
    }
    let token = input.first()?.clone();
    let tokens: TokenStream = std::iter::once(token).collect();
    syn::parse2::<syn::Expr>(tokens.clone()).ok()?;
    bindings.insert(
        name.to_string(),
        Binding::Single {
            tokens,
            frag: "expr".to_string(),
        },
    );
    Some(1)
}

/// Does the follow-sequence match at the start of `input`? Used to terminate a
/// repetition. Only checks literal lookahead (one token) which suffices for the
/// supported shapes; a metavar follow conservatively does not terminate.
fn follow_matches(follow: &[TokenTree], input: &[TokenTree]) -> bool {
    match (follow.first(), input.first()) {
        (Some(f @ TokenTree::Punct(_)), Some(i)) => token_tree_eq(f, i),
        (Some(f @ TokenTree::Ident(_)), Some(i)) => token_tree_eq(f, i),
        (Some(f @ TokenTree::Literal(_)), Some(i)) => token_tree_eq(f, i),
        _ => false,
    }
}

/// Capture one fragment of the given specifier from the start of `input`.
/// `expr`/`ty`/`pat`/`path`/`block` capture greedily up to the follow token (or
/// end); `ident`/`literal`/`tt` capture exactly one token-tree. The captured
/// tokens are validated by re-parsing for `expr` to avoid binding garbage.
fn capture_fragment(
    frag: &str,
    input: &[TokenTree],
    follow: Option<&TokenTree>,
) -> Option<(TokenStream, usize)> {
    match frag {
        "ident" => match input.first() {
            Some(t @ TokenTree::Ident(_)) => Some((std::iter::once(t.clone()).collect(), 1)),
            _ => None,
        },
        "literal" => match input.first() {
            Some(t @ TokenTree::Literal(_)) => Some((std::iter::once(t.clone()).collect(), 1)),
            _ => None,
        },
        "tt" => input
            .first()
            .map(|t| (std::iter::once(t.clone()).collect(), 1)),
        // Greedy fragments: consume token-trees until the follow token matches
        // or input ends. Validate `expr` by re-parsing.
        "expr" | "ty" | "pat" | "pat_param" | "path" | "block" => {
            let mut n = 0;
            while n < input.len() {
                if let Some(f) = follow {
                    if token_tree_eq(f, &input[n]) {
                        break;
                    }
                }
                n += 1;
            }
            if n == 0 {
                return None;
            }
            let captured: TokenStream = input[..n].iter().cloned().collect();
            if frag == "expr" && syn::parse2::<syn::Expr>(captured.clone()).is_err() {
                return None;
            }
            Some((captured, n))
        }
        _ => None,
    }
}

/// Transcribe a macro body, substituting `$name` with bound tokens and expanding
/// `$( ... )...` repetition groups using the repeated bindings.
fn transcribe(body: TokenStream, bindings: &Bindings) -> Result<TokenStream, String> {
    let trees: Vec<TokenTree> = body.into_iter().collect();
    let mut out = TokenStream::new();
    let mut i = 0;
    while i < trees.len() {
        match &trees[i] {
            TokenTree::Punct(p) if p.as_char() == '$' => match trees.get(i + 1) {
                Some(TokenTree::Group(g)) if g.delimiter() == Delimiter::Parenthesis => {
                    let inner = g.stream();
                    let (sep, _op, advance) = parse_rep_suffix(&trees[i + 2..])
                        .ok_or("transcribe: malformed repetition suffix")?;
                    let rounds = repetition_round_count(&inner, bindings)?;
                    for r in 0..rounds {
                        if r > 0 {
                            if let Some(s) = &sep {
                                out.extend(std::iter::once(s.clone()));
                            }
                        }
                        let round_bindings = project_round(bindings, r);
                        out.extend(transcribe(inner.clone(), &round_bindings)?);
                    }
                    i += 2 + advance;
                }
                Some(TokenTree::Ident(name)) => {
                    // `$crate` is the special metavariable for the defining
                    // crate. We resolve macros and calls by their last path
                    // segment, so it carries no information here: drop it (and a
                    // following `::`), turning `$crate::assert_ready!` into
                    // `assert_ready!`.
                    if name == "crate" {
                        i += 2;
                        if matches!(trees.get(i), Some(TokenTree::Punct(p)) if p.as_char() == ':')
                            && matches!(trees.get(i + 1), Some(TokenTree::Punct(p)) if p.as_char() == ':')
                        {
                            i += 2;
                        }
                        continue;
                    }
                    match bindings.get(&name.to_string()) {
                        Some(Binding::Single { tokens, frag }) => {
                            out.extend(transcribe_single_binding(tokens, frag))
                        }
                        Some(Binding::Repeated(_)) => {
                            return Err(format!(
                                "transcribe: `${name}` used outside its repetition"
                            ))
                        }
                        None => return Err(format!("transcribe: unbound metavariable `${name}`")),
                    }
                    i += 2;
                }
                _ => return Err("transcribe: unsupported `$` usage".to_string()),
            },
            TokenTree::Group(g) => {
                // Recurse into nested groups, preserving the delimiter.
                let inner = transcribe(g.stream(), bindings)?;
                out.extend(std::iter::once(TokenTree::Group(proc_macro2::Group::new(
                    g.delimiter(),
                    inner,
                ))));
                i += 1;
            }
            other => {
                out.extend(std::iter::once(other.clone()));
                i += 1;
            }
        }
    }
    Ok(out)
}

fn transcribe_single_binding(tokens: &TokenStream, frag: &str) -> TokenStream {
    if frag == "expr" {
        std::iter::once(TokenTree::Group(proc_macro2::Group::new(
            Delimiter::None,
            tokens.clone(),
        )))
        .collect()
    } else {
        tokens.clone()
    }
}

/// Number of repetition rounds for a `$( ... )` transcriber group: the length of
/// the first repeated binding referenced inside it.
fn repetition_round_count(inner: &TokenStream, bindings: &Bindings) -> Result<usize, String> {
    for name in metavar_names(&inner.clone().into_iter().collect::<Vec<_>>()) {
        if let Some(Binding::Repeated(rounds)) = bindings.get(&name) {
            return Ok(rounds.len());
        }
    }
    Err("transcribe: repetition group references no repeated metavariable".to_string())
}

/// Project the r-th round of every repeated binding to a flat binding set.
fn project_round(bindings: &Bindings, r: usize) -> Bindings {
    let mut out = Bindings::new();
    for (name, b) in bindings {
        match b {
            Binding::Repeated(rounds) => {
                if let Some(round) = rounds.get(r) {
                    if let Some(inner) = round.get(name) {
                        out.insert(name.clone(), inner.clone());
                    }
                }
            }
            Binding::Single { .. } => {
                out.insert(name.clone(), b.clone());
            }
        }
    }
    out
}

/// Names of metavariables (`$name:frag`) appearing in a matcher token sequence.
fn metavar_names(matcher: &[TokenTree]) -> Vec<String> {
    let mut names = Vec::new();
    let mut i = 0;
    while i < matcher.len() {
        match &matcher[i] {
            TokenTree::Punct(p) if p.as_char() == '$' => match matcher.get(i + 1) {
                Some(TokenTree::Ident(name)) => {
                    names.push(name.to_string());
                    i += 2;
                }
                Some(TokenTree::Group(g)) => {
                    names.extend(metavar_names(&g.stream().into_iter().collect::<Vec<_>>()));
                    i += 2;
                }
                _ => i += 1,
            },
            // Recurse into every delimiter group so nested `$e` (e.g. inside
            // `assert_eq!($e, 0)`) is found, not only `$( ... )` groups.
            TokenTree::Group(g) => {
                names.extend(metavar_names(&g.stream().into_iter().collect::<Vec<_>>()));
                i += 1;
            }
            _ => i += 1,
        }
    }
    names
}

/// Structural token-tree equality (delimiter + recursive stream, or token text).
fn token_tree_eq(a: &TokenTree, b: &TokenTree) -> bool {
    match (a, b) {
        (TokenTree::Ident(x), TokenTree::Ident(y)) => x == y,
        (TokenTree::Punct(x), TokenTree::Punct(y)) => x.as_char() == y.as_char(),
        (TokenTree::Literal(x), TokenTree::Literal(y)) => x.to_string() == y.to_string(),
        (TokenTree::Group(x), TokenTree::Group(y)) => {
            x.delimiter() == y.delimiter() && {
                let xs: Vec<TokenTree> = x.stream().into_iter().collect();
                let ys: Vec<TokenTree> = y.stream().into_iter().collect();
                xs.len() == ys.len() && xs.iter().zip(&ys).all(|(p, q)| token_tree_eq(p, q))
            }
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quote::quote;

    fn rules_of(def: TokenStream) -> Vec<MacroRule> {
        parse_rules(def).expect("rules parse")
    }

    #[test]
    fn expands_single_expr_wrapper() {
        // assert_ok!($e:expr) => { assert!($e.is_ok()) }
        let def = quote! { ($e:expr) => { assert!($e.is_ok()) }; };
        let out = expand(&rules_of(def), quote! { foo(x) }).expect("expand");
        assert_eq!(
            out.to_string(),
            quote! { assert!(foo(x).is_ok()) }.to_string()
        );
    }

    #[test]
    fn expr_fragment_substitution_preserves_method_receiver_boundary() {
        // `$other:expr` must be transcribed as one opaque expression fragment.
        // Otherwise `$other.get(..)` with `1..2` reparses as `1..(2.get(..))`,
        // leaking a wrong-sorted range endpoint downstream before desugar owns it.
        let def = quote! { ($other:expr, $slice:expr) => { $other.get(&$slice as &[_]) }; };
        let out = expand(&rules_of(def), quote! { 1..2, [0, 1] }).expect("expand");
        let expr: syn::Expr = syn::parse2(out).expect("expanded expression parses");
        let call = match expr {
            syn::Expr::MethodCall(call) => call,
            other => panic!("expanded `$other.get` must parse as a method call, got {other:?}"),
        };
        assert_eq!(call.method, "get");
        let receiver_is_range = match call.receiver.as_ref() {
            syn::Expr::Range(_) => true,
            syn::Expr::Group(group) => matches!(group.expr.as_ref(), syn::Expr::Range(_)),
            _ => false,
        };
        assert!(
            receiver_is_range,
            "the whole `1..2` expr fragment must be the receiver, got {:?}",
            call.receiver
        );
    }

    #[test]
    fn expands_typed_two_expr_const_safe_shape() {
        // assert_eq_const_safe!($t:ty: $l:expr, $r:expr) => { assert_eq!($l, $r) }
        let def = quote! { ($t:ty: $l:expr, $r:expr) => { assert_eq!($l, $r) }; };
        let out = expand(&rules_of(def), quote! { u8: make(), 42 }).expect("expand");
        assert_eq!(
            out.to_string(),
            quote! { assert_eq!(make(), 42) }.to_string()
        );
    }

    #[test]
    fn expands_single_rule_pub_macro_shape() {
        let def = quote! { ($($arg:tt)*) { assert!($($arg)*); } };
        let out = expand(&rules_of(def), quote! { value.is_ok() }).expect("expand");
        assert_eq!(
            out.to_string(),
            quote! { assert!(value.is_ok()); }.to_string()
        );
    }

    #[test]
    fn expands_rule_list_pub_macro_with_pat_param() {
        let def = quote! {
            ($left:expr, $(|)? $( $pattern:pat_param )|+ $(,)?) => {{
                match $left {
                    $( $pattern )|+ => {}
                    _ => { panic!(); }
                }
            }},
        };
        let out = expand(&rules_of(def), quote! { value, Some(_) }).expect("expand");
        assert!(out.to_string().contains("match value"), "{out}");
        assert!(out.to_string().contains("Some (_)"), "{out}");
    }

    #[test]
    fn picks_correct_rule_by_literal_token() {
        let def = quote! {
            (ok, $e:expr) => { assert!($e.is_ok()) };
            (err, $e:expr) => { assert!($e.is_err()) };
        };
        let out = expand(&rules_of(def), quote! { err, foo(x) }).expect("expand");
        assert_eq!(
            out.to_string(),
            quote! { assert!(foo(x).is_err()) }.to_string()
        );
    }

    #[test]
    fn expands_repetition_with_separator() {
        // all_eq!($($e:expr),*) => { $( assert_eq!($e, 0); )* }
        let def = quote! { ($($e:expr),*) => { $( assert_eq!($e, 0); )* }; };
        let res = expand(&rules_of(def), quote! { a, b, c });
        let out = res.unwrap_or_else(|e| panic!("expand err: {e}"));
        assert_eq!(
            out.to_string(),
            quote! { assert_eq!(a, 0); assert_eq!(b, 0); assert_eq!(c, 0); }.to_string()
        );
    }

    #[test]
    fn expands_plus_repetition_without_separator_into_block_repetition() {
        let def = quote! {
            ($($N:expr)+) => {
                $({
                    type Array = [u8; $N];
                    let mut array: Array = [0; $N];
                    let slice: &[u8] = &array[..];
                    let result = <&Array>::try_from(slice);
                    assert_eq!(&array, result.unwrap());
                })+
            };
        };
        let out =
            expand(&rules_of(def), quote! { 0 1 2 }).unwrap_or_else(|e| panic!("expand err: {e}"));
        let expanded = out.to_string();
        assert!(expanded.contains("assert_eq"), "{expanded}");
        assert!(expanded.contains("[u8 ; 0]"), "{expanded}");
        assert!(expanded.contains("[u8 ; 2]"), "{expanded}");
    }

    #[test]
    fn refuses_when_no_rule_matches() {
        let def = quote! { (ok, $e:expr) => { assert!($e.is_ok()) }; };
        assert!(expand(&rules_of(def), quote! { nope }).is_err());
    }

    #[test]
    fn refuses_garbage_expr_capture() {
        // `$e:expr` followed by end; input that is not a valid expr must not bind.
        let def = quote! { ($e:expr) => { assert!($e) }; };
        // `+ +` is not a valid expression.
        assert!(expand(&rules_of(def), quote! { + + }).is_err());
    }

    #[test]
    fn binds_metavars_inside_a_delimiter_group() {
        // The `assert_chunks!` shape: a `$string:expr` then a repetition whose
        // inner matcher is a parenthesized group `($valid:expr, $invalid:expr)`.
        // The matcher must RECURSE into the input's `(...)` group to bind the
        // inner metavars rather than fail a structural length compare.
        let def = quote! {
            ( $string:expr, $(($valid:expr, $invalid:expr)),* $(,)? ) => {{
                $(
                    assert_eq!($valid, c.valid());
                    assert_eq!($invalid, c.invalid());
                )*
            }};
        };
        let out = expand(&rules_of(def), quote! { b"hello", ("hello", b"") })
            .unwrap_or_else(|e| panic!("expand err: {e}"));
        assert_eq!(
            out.to_string(),
            quote! {{
                assert_eq!("hello", c.valid());
                assert_eq!(b"", c.invalid());
            }}
            .to_string()
        );
    }

    #[test]
    fn binds_metavars_inside_group_across_multiple_rounds() {
        // Two repetition rounds, each a `(...)` group: confirms the recursive
        // group bind composes with `match_repetition` round projection.
        let def = quote! {
            ( $s:expr, $(($v:expr, $i:expr)),* $(,)? ) => {{
                $( assert_eq!($v, $i); )*
            }};
        };
        let out = expand(&rules_of(def), quote! { src, ("a", 1), ("b", 2) })
            .unwrap_or_else(|e| panic!("expand err: {e}"));
        assert_eq!(
            out.to_string(),
            quote! {{ assert_eq!("a", 1); assert_eq!("b", 2); }}.to_string()
        );
    }

    #[test]
    fn literal_group_still_matches_exactly() {
        // DISCRIMINATION: a matcher group with NO metavar (`()`) must still
        // match by exact equality, and a non-empty input group must NOT match
        // it -- the recursive path is gated on `matcher_group_has_metavar`.
        let def = quote! { ((), $e:expr) => { assert!($e) }; };
        let ok = expand(&rules_of(def.clone()), quote! { (), foo() }).expect("expand");
        assert_eq!(ok.to_string(), quote! { assert!(foo()) }.to_string());
        // `(x)` is a non-empty group: it must NOT match the literal `()` group.
        assert!(expand(&rules_of(def), quote! { (x), foo() }).is_err());
    }

    #[test]
    fn group_arity_mismatch_bails() {
        // DISCRIMINATION: a `($a:expr, $b:expr)` matcher group must NOT match a
        // single-element input group `(x)` -- the inner match must consume the
        // ENTIRE input group stream, so a 1-element group is a mismatch.
        let def = quote! {
            ( $(($a:expr, $b:expr)),* ) => {{ $( assert_eq!($a, $b); )* }};
        };
        assert!(expand(&rules_of(def), quote! { (x) }).is_err());
    }

    #[test]
    fn group_delimiter_mismatch_bails() {
        // DISCRIMINATION: a parenthesized matcher group must NOT match a
        // bracketed input group even when the inner metavars would otherwise
        // bind.
        let def = quote! {
            ( $(($a:expr, $b:expr)),* ) => {{ $( assert_eq!($a, $b); )* }};
        };
        assert!(expand(&rules_of(def), quote! { [x, y] }).is_err());
    }

    #[test]
    fn strips_dollar_crate_in_transcription() {
        // assert_ready_eq!($e:expr, $expect:expr) => { $crate::assert_ready!($e) ... }
        let def = quote! { ($e:expr) => { $crate::assert_ready!($e) }; };
        let out = expand(&rules_of(def), quote! { foo() }).expect("expand");
        // $crate:: is stripped entirely; the macro resolves by name.
        assert_eq!(out.to_string(), quote! { assert_ready!(foo()) }.to_string());
    }
}

#[cfg(test)]
mod trailing_separator_tests {
    use super::*;
    use quote::quote;

    fn rules_of(def: TokenStream) -> Vec<MacroRule> {
        parse_rules(def).expect("rules parse")
    }

    // The exact `assert_chunks!` matcher: a leading expr, then a separated
    // repetition of `(expr, expr)` groups, then an OPTIONAL trailing comma.
    fn chunks_def() -> TokenStream {
        quote! {
            ( $string:expr, $(($valid:expr, $invalid:expr)),* $(,)? ) => {{
                $(
                    assert_eq!($valid, $invalid);
                )*
            }};
        }
    }

    #[test]
    fn repetition_groups_with_trailing_comma_expand() {
        // The corpus shape: three `(.., ..)` groups AND a trailing comma. The
        // repetition must NOT swallow the trailing comma as a separator (which
        // would leave a round with no input and fail the match); `$(,)?` eats it.
        let out = expand(
            &rules_of(chunks_def()),
            quote! { b"H", ("Hello", 1), (" There", 2), (" Goodbye", 3), },
        )
        .unwrap_or_else(|e| panic!("trailing-comma multi-group expand err: {e}"));
        assert_eq!(
            out.to_string(),
            quote! {{
                assert_eq!("Hello", 1);
                assert_eq!(" There", 2);
                assert_eq!(" Goodbye", 3);
            }}
            .to_string()
        );
    }

    #[test]
    fn repetition_groups_without_trailing_comma_expand() {
        // Same matcher, no trailing comma: the `$(,)?` simply matches zero.
        let out = expand(&rules_of(chunks_def()), quote! { b"H", ("a", 1), ("b", 2) })
            .unwrap_or_else(|e| panic!("no-trailing-comma expand err: {e}"));
        assert_eq!(
            out.to_string(),
            quote! {{ assert_eq!("a", 1); assert_eq!("b", 2); }}.to_string()
        );
    }

    #[test]
    fn single_group_with_trailing_comma_expands() {
        // The `assert_chunks!(b"hello", ("hello", b""))` / `(.., ..),` minimal
        // shape: one group, optional trailing comma both present and absent.
        let no_comma = expand(&rules_of(chunks_def()), quote! { b"h", ("hello", 0) })
            .expect("single group no comma");
        let with_comma = expand(&rules_of(chunks_def()), quote! { b"h", ("hello", 0), })
            .expect("single group trailing comma");
        assert_eq!(no_comma.to_string(), with_comma.to_string());
        assert_eq!(
            no_comma.to_string(),
            quote! {{ assert_eq!("hello", 0); }}.to_string()
        );
    }

    #[test]
    fn doubled_trailing_separator_does_not_match() {
        // DISCRIMINATION: `$(,)?` matches AT MOST ONE trailing comma. A doubled
        // trailing `,,` leaves an unconsumed token, so the whole input is not
        // consumed -> no rule matches (we must not over-accept malformed input).
        assert!(
            expand(&rules_of(chunks_def()), quote! { b"h", ("a", 1),, }).is_err(),
            "a doubled trailing separator must not match"
        );
    }
}
