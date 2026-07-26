# Contributing to Sugar

Sugar is a polyglot protocol. The thesis only holds if the protocol bytes match across implementations. Every contribution is, ultimately, a claim about byte-determinism: that the bytes a contributor's code emits agree with the bytes every other implementation emits for the same canonical formula.

This page is the contributor on-ramp. Pick the row that matches what you want to do.

## I want to...

| Goal | Start here | Difficulty |
|---|---|---|
| Add support for a new host language | [porting-to-a-new-language.md](porting-to-a-new-language.md) | High; multi-week |
| Write a kit for an existing language | [writing-a-kit/](writing-a-kit/) | Medium |
| Write a lift adapter for an annotation library | [writing-a-lift-adapter/](writing-a-lift-adapter/) | Low to medium |
| Write an LSP plugin for an existing kit | [writing-an-LSP-plugin.md](writing-an-LSP-plugin.md) | Low to medium |
| Write a prover backend (Lean, TLA+, CBMC) | [writing-a-prover-backend.md](writing-a-prover-backend.md) | High |
| Improve adapter coverage for an existing kit | [adapter-coverage-rubric.md](adapter-coverage-rubric.md) | Low |
| Propose a spec change | [proposing-a-spec-change.md](proposing-a-spec-change.md) | Varies |
| Cut a release | [release-process.md](release-process.md) | Operational |
| Build from source | [build.md](build.md) | Trivial |

## The social contract

Every implementation in Sugar is held to one rule: **the bytes you emit for a canonical formula must equal the bytes any other implementation emits for the same canonical formula**. The contract is enforced by the conformance harness; running `make ci` re-derives every spec CID, mints every kit's self-contracts, and fails on any drift.

This means contributions land or don't land on a single empirical question: does your code produce the canonical bytes? The harness has a `conformance` target for each kit. Make it green, and the kit is conformant. Don't make it green, and the kit is broken, regardless of how good the code looks.

The social contract is the conformance harness. Everything else is convention.

## What contribution looks like

Three categories, in increasing scope:

### 1. Lift adapter for an existing library

Pick a source library that emits structured annotations: a Rust attribute crate, an npm validator, a Python decorator library, a Java annotation set. Write a walker that lifts those annotations into canonical IR. Run the conformance harness. Open a PR.

This is the lowest-stakes contribution. It extends one kit's coverage without changing protocol semantics. Most v1.2 work falls in this bucket.

See [writing-a-lift-adapter/](writing-a-lift-adapter/).

### 2. Kit for an existing host language

The kit is the per-language authoring substrate: IR types, canonicalizer, claim envelope codec, proof envelope codec, self-contracts package, bridge IR. Every kit must pass the cross-language conformance fixtures: feed the same canonical formula in, get the same bytes out.

This is medium-stakes. Get the conformance fixtures green and the kit ships. Self-contracts attestation closes the loop: your kit's mint must hash to a CID pinned in `make conformance`.

See [writing-a-kit/](writing-a-kit/) for the six-step series.

### 3. Port to a new host language

Combines (1) and (2) plus the language-specific decisions: what's the authoring surface (decorator macros, attributes, comment annotations), how does the toolchain integrate (cargo / pnpm / pip / Maven / dotnet / gem), what's the LSP story, how do dependencies work. This is multi-week work.

See [porting-to-a-new-language.md](porting-to-a-new-language.md).

## Code style and review

Per-language idiomatic. In the Rust workspace, `cargo fmt` is enforced -- CI runs `cargo fmt --all -- --check` (`.github/workflows/ci.yml`). `cargo clippy` is recommended but **not gated**: there is no clippy step in any Makefile target or workflow, and the workspace does not currently pass `-D warnings`. Do not read a clean CI run as a clippy-clean tree. The TypeScript workspace uses Prettier. Each kit's directory has its own conventions; follow what's there.

Reviews focus on three questions, in order:

1. **Does the conformance harness pass?** This is non-negotiable. A red harness blocks the merge.
2. **Is the change scoped?** A lift adapter PR should not touch the canonicalizer. A canonicalizer PR should not touch lift adapters.
3. **Is the contribution complete?** Tests. Docs. A CHANGELOG entry where applicable.

## Getting help

The repository has a [`docs/contributing/`](.) directory that this overview indexes. If a doc you need doesn't exist, file an issue describing what you're trying to do; the doc gap is a real bug, not just missing prose.

For build issues, see [`build.md`](build.md). For protocol questions, see [`docs/explanation/`](../explanation/) and [`protocol/specs/`](../../protocol/specs/).
