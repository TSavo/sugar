# rust-coretests-report — the honest coverage ledger

This is the **measuring stick** for the Rust assertion-lift kit: it runs
`sugar lift --report` over the Rust standard library's `coretests` corpus
(vendored under [`corpus/tests`](corpus/tests), lifted under the pinned
`nightly-2026-02-07` toolchain the corpus's `#![feature(...)]` prelude assumes)
and prints how every assertion locus is honestly accounted.

```sh
./run.sh              # full corpus
SUBDIR=iter ./run.sh  # one subtree, faster
```

It exists **in the repo, in the open**, because a measuring stick you keep in
`/tmp` is no measuring stick at all — you can't see the dark you're not allowed
to find.

## What the ledger means

`source audit: loci=N warranted=… support=… refused=… refuted=… unresolved=…`

- **warranted** — the locus lifted to a FOL fact (a real, checkable obligation).
- **unresolved** — *we have no Sugar for this shape yet.* This is the honest
  dark. Progress = driving `unresolved → 0` with real lifters, not hiding it.
- **refused / refuted** — loudly-bounded-lossy (a named effect / a contradiction
  twin); a sound "no", not a silent drop.
- **support** — **INERT source ONLY**: comments, doc-comments, compiler pragmas,
  `Pass`, `TypeIgnore`, directives. Things that carry no assertion to prove.

## The rule this corpus enforces

> **`support` is NOT the place to hide "we don't have Sugar for that yet."**

A `FunctionDef` / `Import` / `ClassDef` is *not* inert — it can contain unproven
assertions — so it must never be bucketed as `support`. Counting it as `support`
credits a hidden hole as covered: a fake denominator. Such loci belong in
`unresolved`, where the gap is visible and someone has to write the Sugar to
close it. The lift report enforces this (`is_inert_support_ast_kind`); this
corpus is how we keep it honest end-to-end.
