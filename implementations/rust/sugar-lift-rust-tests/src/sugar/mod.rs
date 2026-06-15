// SPDX-License-Identifier: Apache-2.0
//
// The `Sugar` hierarchy, one file per class (T 2026-06-14). The doctrine
// reified as types, decomposed from the lib.rs monolith into a module tree so
// each construct (struct + impl + decompose helper) lives in its own file. The
// trait `Sugar`, the shared `Desugared`/`ConstVal`/`SugarCtx` spine, and
// `const_eval` stay in lib.rs, alongside the black-box `lifter_key_tests`
// integration suite (the tests drive the public `lift_file` API end-to-end, so
// they are not per-class unit tests and stay with the dispatch spine).
//
// NOTE on `map`/`filter`: there is NO standalone `MapSugar`/`FilterSugar` type
// in this codebase -- Map/Filter/SkipWhile/TakeWhile are ARMS of the single
// `enum Adaptor` (applied by `apply_one_adaptor`). Fragmenting one enum across
// files would break the type, so those arms live with the enum in `adaptor.rs`.
// `map.rs`/`filter.rs` are therefore intentionally NOT created (the literal
// per-arm split is unsound for a behaviour-preserving move); the adaptor arms
// are documented at their definition in `adaptor.rs`.

// ─────────────────────────────────────────────────────────────────────────────
// The `Sugar` hierarchy (T 2026-06-14). The doctrine reified as types.
//
// stdlib IS sugar; a method-call chain / for-loop is a COMPOSITE TREE of `Sugar`
// nodes, each owning its own `.desugar()` (Interpreter pattern; the chain of
// responsibility falls out of the composition). `decompose` builds the tree by
// recursively decomposing a node's children into inner Sugars; `.desugar()` walks
// inward until `LiteralSugar` bottoms out OR some node returns `None` (BAIL). The
// structure ENFORCES the one predicate: the only way to produce a `Desugared` is
// to reach literals through every layer (no fake-discharge); any layer's `None`
// is the happy refuse.
//
// `Desugared` is a (value, warrant) pair. There are two value flavors, glued to
// the SAME warrant rope:
//   * `Seq` -- a finite element sequence (the literal floor, possibly synthetic:
//     a filter/map output the vendor never typed, warranted by the composed
//     sugar that minted it). Each element keeps BOTH its source `Expr` (for EUF
//     term translation / faithful substitution) AND its `ConstVal` when exactly
//     evaluable; a transforming adaptor REQUIRES the `ConstVal` or it bails.
//   * `Constraints` -- the emitted finite conjunction (a fold/for_each/for-loop
//     terminal), the assert-macro count it accounts, and its warrant (the memento
//     name). This is the lift; the warrant ties it back to the sugar.
//
// EXACT-OR-BAIL is structural: `ConstVal` has no Float/Str variant, so a
// non-const element bails; `Option<Desugared>` IS the bail. A wrong BAIL is a
// safe under-claim; a wrong DIG would be a fake-discharge, so we never guess.

pub(crate) mod adaptor;
pub(crate) mod conditional;
pub(crate) mod fold;
pub(crate) mod foreach;
pub(crate) mod forall;
pub(crate) mod literal;
