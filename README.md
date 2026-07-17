# Sugar

**Sugar in, `.proof` out.** Sugar reads the surface your code already has — unit
tests, assertions, function bodies — and turns it into a signed,
content-addressed `.proof` of what your software actually does. No spec
language, no annotations, no changes to your code, and no single-language
lock-in: the same pipeline lifts Rust, Python, and Java today.

A `.proof` is a portable, recomputable artifact. Anyone can verify it from its
bytes, hashes (BLAKE3-512 CIDs), signatures, and witnesses — no registry, no
vendor to trust. That makes three things practical that weren't:

- **Honest dependency bumps.** `sugar diff` compares two versions by *behavior*,
  not text or version number, and classifies every behavior as held, renamed,
  new, or lost — so a "minor" release that changes what a function does lights
  up before it reaches prod.
- **Checked assumptions.** `sugar prove` hands z3 your callsite's assumption and
  the dependency's own lifted contract and asks whether both can be true at
  once. A wrong assumption is refused at the callsite, before anything runs.
- **Cross-language guarantees.** Contracts are lifted into one shared logic, so
  a Rust caller can be checked against a Python library's proven behavior at
  the same callsite.

Sugar never becomes the authority on what your code means. The CLI owns no
language semantics; per-language **kits** do the lifting, and a kit only ever
rules by citing the vendor — the vendor's own tests, compiler, and semantics.
What a kit can't see is reported honestly as an effect, residue, or refusal,
never painted green.

## Quick start

Sugar is build-from-source today (crates.io publishing is future work). You
need a Rust toolchain.

```sh
git clone https://github.com/tsavo/sugar.git
cd sugar

# Install the CLI
cargo install --path implementations/rust/sugar-cli
sugar --version

# Build the workspace binaries the demos invoke
# (the demo run.sh scripts call implementations/rust/target/debug/… directly)
(cd implementations/rust && cargo build)
```

Then run a demo. Each `run.sh` mints, proves, and verifies end to end; the
numpy demos provision their own venv on first run:

```sh
examples/numpy-vendor/run.sh
```

For the full clone-to-verified-`.proof` walkthrough, read
[docs/getting-started.md](docs/getting-started.md).

## The core verbs

`sugar --help` is the authoritative list; the command surface is still moving.
The verbs you'll use first:

| Command | What it does |
|---|---|
| `sugar mint` | Run the configured lift plugins and write signed `.proof` artifacts. |
| `sugar prove` | Six-stage verifier: load proofs, resolve dependency proofs through kits, enumerate callsites, conjoin same-named contracts, solve obligations with z3, recompute witnesses. |
| `sugar verify` | Verify a kit end to end and emit a signed per-claim receipt (the gate verb). |
| `sugar diff <a> <b>` | Compare two proof sets by behavior; classify held / renamed / new / lost and report the implied semver bump. `--require <bump>` enforces honest semver; `--frozen` fails on any delta. |
| `sugar dump` | Pretty-print a `.proof` envelope. |
| `sugar hash` | Compute the BLAKE3-512 CID of a file or stdin. |
| `sugar implicate` | Mint a signed implication memento (`post(B) → pre(A)`, checked by z3) — the composition edge. |
| `sugar init` | Scaffold a project (`sugar.toml`, `.sugar/`, sample invariant, GitHub Action). |
| `sugar doctor` | Validate a kit's config and manifest wiring before a run. |

Other subcommands (`lift`, `compose`, `bind`, `emit`) cover the lower-level
lift and concept-binding pipeline; see `sugar --help`.

## How it works, in one paragraph

Each kit lifts its language surface into one first-order logic: vendor-tested
assertions become formulas over shared sorts, execution order is thrown away,
and the result is canonicalized and content-addressed — so "did the behavior
change?" becomes a 64-byte hash comparison. Verification is one z3 question per
obligation: can the claim and the lifted body be true at once? Every warrant in
a `.proof` is either **stated** (the vendor's own sworn assertion, transported
with its citation) or **derived** (computed from stated facts by cited rules),
and every verdict pins the kit, corpus, and toolchain it ran under by CID.
Effects — files, sockets, clocks, FFI — stop the map and are drawn as typed
holes rather than hidden. The full doctrine lives in [AGENTS.md](AGENTS.md);
the vocabulary lives in [SHARED-LANGUAGE.md](SHARED-LANGUAGE.md).

## Demos

There are ~90 runnable examples in [examples/](examples/); they are the honest
picture of what works end to end today. Highlights:

| Demo | What it shows |
|---|---|
| [examples/numpy-vendor/](examples/numpy-vendor/) | A whole library vendored: every module-level numpy function lifted into one `.proof`, no shim; a consumer `verify` recomputes the witnesses. |
| [examples/numpy-showcase/](examples/numpy-showcase/) | One operation (`numpy.rot90`) discharged two ways: consistency via z3, and the degenerate twin refused by both z3 UNSAT and witness recompute. |
| [Inheritance e2e test](implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py) | A consumer inherits numpy's contract and is refused when it contradicts it. |

## Repository layout

| Path | Contents |
|---|---|
| `implementations/rust/` | The canonical implementation, including the `sugar` CLI (`sugar-cli`). |
| `implementations/python/`, `implementations/java/` | Python and Java kits and their tests. |
| `examples/` | Runnable end-to-end demos, one directory per scenario. |
| `docs/` | Getting started, reference, contributing, papers, security, audits. |
| `protocol/` | Protocol definitions. |
| `conformance/`, `tests/` | Conformance and test suites. |
| `AGENTS.md` | The full doctrine: invariants, rules, and design constraints. |
| `SHARED-LANGUAGE.md` | The project vocabulary. |

## Status

- The **canonical implementation** is the Rust CLI in
  `implementations/rust/sugar-cli`. The protocol catalog is embedded in the
  binary and surfaced by `sugar self-check`; the binary, not prose, is the
  authority for the catalog CID.
- **Language coverage is empirical and uneven.** If it is not a passing example
  in [examples/](examples/), treat it as in progress. Unknown, unsupported, or
  lossy surfaces are reported as residue, loss, or refusal — never silently
  passed.
- The durable units are `.proof` envelopes, signed mementos, and the CIDs of
  sources, witnesses, contracts, attestations, contract sets, and the protocol
  catalog. No RNG, no clocks: artifacts are values, re-verifiable by anyone.
- Sugar applies itself: the CLI mints proof data from its own tests and
  assertions. See
  [docs/self-application/2026-05-28-snake-eats-tail.md](docs/self-application/2026-05-28-snake-eats-tail.md).

## What Sugar is not

- **Not a replacement for tests.** Tests are much of the evidence kits lift.
- **Not a replacement for Kani, Prusti, Coq, Lean, F\*, Dafny, TLA+, or z3.**
  Those tools produce evidence; Sugar gives evidence a portable,
  content-addressed, recomputable supply chain.
- **Not a central registry.** Proofs verify from their bytes and your local
  policy; a server may index them for convenience but is never the authority.
- **Not a claim of total coverage.** Kit coverage is empirical, and the gaps
  are reported, not hidden.

## Going deeper

| Goal | Read |
|---|---|
| Clone → verified `.proof` | [docs/getting-started.md](docs/getting-started.md) |
| Everything that runs today | [examples/](examples/) |
| Build Sugar from source (polyglot Make targets, system deps) | [docs/contributing/build.md](docs/contributing/build.md) |
| The vocabulary | [SHARED-LANGUAGE.md](SHARED-LANGUAGE.md) |
| The full doctrine | [AGENTS.md](AGENTS.md) |
| The paper ladder (whitepaper onward) | [docs/papers/README.md](docs/papers/README.md) |
| All docs | [docs/](docs/) |

## License

Licensed under either of the [Apache License, Version 2.0](LICENSE-APACHE) or
the [MIT license](LICENSE-MIT), at your option. Unless you explicitly state
otherwise, any contribution intentionally submitted for inclusion in this work
by you shall be dual licensed as above, without any additional terms or
conditions.

Proof artifacts you generate with Sugar are yours; no license attaches to them.
