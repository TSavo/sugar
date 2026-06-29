<!--
  Docs home / map. House rule for everything under docs/: receipts, not assertions.
  Link a page only if it exists and is grounded in something that runs. Anything
  not yet real is listed as *returning* (a named gap), never linked as if it ships.
-->
# Sugar documentation

**Sugar makes software honest** — it turns the surface you already wrote (your
tests, your function bodies, your annotations and schemas) into signed,
content-addressed `.proof`s of *behavior*, in any language, and tells you exactly
what it could **not** prove. Read the [README](../README.md) for the why; this page
is the map.

> **House rule for everything under `docs/`: receipts, not assertions.** Every
> user-facing page is backed by something that runs in this repo. Anything not yet
> real is labeled *returning* — a known gap — never linked as if it exists. A hole
> beats a liar's map.

## Start here

| You want to… | Go to |
|---|---|
| Understand what Sugar is, and why | [README](../README.md) |
| Get from clone to a verified `.proof` | [getting-started.md](getting-started.md) |
| Learn the vocabulary (sugar, lift, contract, oracle…) | [SHARED-LANGUAGE.md](../SHARED-LANGUAGE.md) |
| See everything that runs today | [examples/](../examples/) |

## By audience

### Evaluating Sugar
- [README](../README.md) — the thesis: *honest, not correct*; the residual is the product.
- [getting-started.md](getting-started.md) — produce → verify → inherit, on demos that run end to end.
- [examples/](../examples/) — the runnable receipts (numpy-vendor headline, two-way discharge showcase, the inheritance capstone, and more).
- [explanation/concepts.md](explanation/concepts.md) — the mental model (sugar & contract, lift/lower, the trinity, CID, the honest trichotomy), distilled from the dictionary.
- [explanation/rendezvous.md](explanation/rendezvous.md) — how kits register interest in a project: census → discover → declare → component plan (the front of the pipeline).
- *Returning:* the rest of `explanation/` — *why a contract beats a test*, the `sugar diff` dragons report (currently README sections, being extracted).

### Using Sugar on your code
- [examples/](../examples/) — start from the `run.sh` closest to your case; each mints, proves, and verifies end to end.
- [how-to/publish-and-inherit-a-proof.md](how-to/publish-and-inherit-a-proof.md) — ship a `.proof` for your library; consume and inherit one, cross-language.
- [how-to/behavioral-semver.md](how-to/behavioral-semver.md) — catch behavior drift on upgrade: `sugar diff --require`/`--frozen`, `cargo sugar` in CI, the `sugar-check` pre-commit hook.
- [reference/cli.md](reference/cli.md) — the full CLI surface (all 21 verbs), grounded against the dispatch table.
- [`.proof` file format](../protocol/specs/2026-04-30-proof-file-format.md) — the canonical spec: what's in a `.proof`, the integrity rules, walking one.
- [reference/per-language-status.md](reference/per-language-status.md) — the kits and the runnable evidence per language (no coverage numbers; the examples are the test of record).

### Extending Sugar (a new kit, lifter, or backend)
- [contributing/overview.md](contributing/overview.md) — the lay of the land.
- [contributing/writing-a-kit/](contributing/writing-a-kit/) — implement a language kit.
- [contributing/writing-a-lift-adapter/](contributing/writing-a-lift-adapter/) — lift a native surface into ProofIR (the mechanics).
- **[contributing/lifting-rules.md](contributing/lifting-rules.md)** — the soundness laws a lifter must obey; read before shipping a kit/lifter.
- [contributing/lifting-vocabulary.md](contributing/lifting-vocabulary.md) — the lifting ontology (fact, dig, effect, bridge, implication, source oracle, mementos, atoms) and how each lands in ProofIR.
- [contributing/factory-sugar-floor.md](contributing/factory-sugar-floor.md) — the recommended lifter shape (design guideline) that satisfies those laws cleanly.
- [contributing/writing-a-prover-backend.md](contributing/writing-a-prover-backend.md) — add an IR-compiler backend.
- [contributing/writing-an-LSP-plugin.md](contributing/writing-an-LSP-plugin.md) · [contributing/porting-to-a-new-language.md](contributing/porting-to-a-new-language.md)
- [contributing/build.md](contributing/build.md) — build from source, polyglot Make targets, system deps.

### Going deep
- [papers/](papers/README.md) — the 26-paper ladder (narrative, not API surface).
- [security/threat-model.md](security/threat-model.md) — what Sugar catches and what it does not; see also [security/](security/) for multi-dimensional pinning, solver/adapter trust, and the `binaryCid` catches/doesn't pages.
- [self-application/](self-application/) — Sugar proving Sugar: [GOAL-sugar-proves-sugar.md](self-application/GOAL-sugar-proves-sugar.md), the assertion-accounting ledger, the snake-eats-tail runs.
- [INVARIANTS.md](INVARIANTS.md) · [sugar-invariants.md](sugar-invariants.md) — the soundness invariants the whole product rests on (`silent == 0`, `false_discharges == 0`).

## Internal (not user-facing)

`plans/`, `audits/`, `incidents/`, `internal/`, `research/`, `_surface/` — working
notes, grounding passes, and process. Kept out of the user tree on purpose; browse
if you're working *on* Sugar, skip if you're working *with* it.

## The honest gaps (returning)

The user-facing `explanation/`, `reference/`, and `how-to/` layers were removed when
they drifted ahead of the implementation — a hole beats a liar's map. They return
page by page as each is grounded in a path that runs end to end.
[getting-started.md](getting-started.md) is the first one back.
