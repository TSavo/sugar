// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Source-locus metadata for arrivals, contracts, and other mementos.
// Per #372 part 1.
//
// The Locus DATA type lives in libsugar (so it can be reused by every
// language lifter that emits FunctionContractMemento bodies). This module
// re-exports it for walk's existing import paths and supplies the
// syn-using `from_span` constructor that turns a `proc_macro2::Span` into
// a libsugar Locus. Keeping the constructor here avoids pulling syn
// into libsugar while keeping walk-internal call sites unchanged.

pub use libsugar::compose::Locus;
use proc_macro2::Span;

/// Build a `Locus` from a syn::Span and an optional file path.
pub fn from_span(span: Span, file: Option<&str>) -> Locus {
    let start = span.start();
    Locus {
        file: file.map(|s| s.to_string()),
        line: start.line,
        col: start.column,
    }
}

/// Adapter helper trait so existing callers writing
/// `Locus::from_span(span, file)` keep working without touching the
/// call sites. We add an inherent-style associated function via a
/// helper trait to avoid re-defining the struct in walk.
pub trait LocusFromSpanExt {
    fn from_span(span: Span, file: Option<&str>) -> Locus;
}
impl LocusFromSpanExt for Locus {
    fn from_span(span: Span, file: Option<&str>) -> Locus {
        from_span(span, file)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locus_extracts_line_col_from_span() {
        let src = "fn foo() {}\nfn bar() {}\n";
        let file: syn::File = syn::parse_str(src).unwrap();
        let bar_fn = file
            .items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == "bar" => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .unwrap();
        let span = syn::spanned::Spanned::span(&bar_fn.sig.ident);
        let locus = from_span(span, Some("test.rs"));
        assert_eq!(locus.file.as_deref(), Some("test.rs"));
        assert_eq!(locus.line, 2);
    }

    #[test]
    fn locus_unknown_round_trips_through_canonical() {
        let l = Locus::unknown();
        assert!(l.is_unknown());
        let v = l.to_value();
        let bytes = sugar_canonicalizer::encode_jcs(&v);
        assert!(bytes.contains("\"file\":null"));
        assert!(bytes.contains("\"line\":0"));
    }
}
