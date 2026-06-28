# Proposing a spec change

> ⚠️ **One stale reference (2026-06-28):** the mention of `sugar verify-protocol`
> below names a **removed** command — it is no longer a CLI subcommand. The
> catalog-mismatch behavior it described still holds; the verb to invoke it is gone.

A spec change is any change to a document in `protocol/specs/`. It alters the protocol's content-addressed substrate. Because each spec is content-addressed, a change always changes a CID, which always cascades into kit re-mints, fixture updates, and an eventual catalog version bump.

This is the most consequential kind of contribution. This doc walks the process.

## What counts as a spec change

The specs at `protocol/specs/` cover:

- The IR formal grammar (CDDL).
- The proof file format.
- The handshake algorithm.
- The lattice tractability theorem.
- The signatures and non-repudiation spec.
- The kit standard.
- Extension protocols such as PEP, GCP, TDP, ORP, CBP, and FRP.
- Reference contract registries, prover backend interfaces, and other claim families as they become cataloged.

A change to any of these is a spec change. Common triggers:

1. **A new IR primitive is needed.** A common annotation pattern (e.g., temporal predicates, regex unions) doesn't fit the current grammar.
2. **A canonical predicate name needs to be standardized.** Two adapters chose different names for the same semantics; the canonical name must be picked.
3. **A clarification is needed.** A spec is ambiguous and two implementations diverged; the spec needs to disambiguate.
4. **A bug fix.** The spec says something incorrect (rare but real).
5. **A new bridge anchor.** The reference-contracts library wants to add `ref-uuid-v1` or similar.
6. **A new extension body convention.** A protocol/tooling surface needs a signed claim family, such as a grammar conformance claim, realizer output, or proof-file conformance witness.

## Before proposing

1. **Read the existing spec.** Many "missing" features are already there.
2. **Search for prior discussion.** GitHub issues, draft RFCs, commit history.
3. **Construct a worked example.** "I have annotation X in library Y, here's the canonical IR I think it should produce, here's the spec change that makes that canonical IR expressible." Without a worked example, the proposal is too abstract.
4. **Check whether a workaround exists.** Often a new primitive isn't needed because a composition of existing primitives works. Lattice tractability prefers fewer primitives over more.

## The proposal shape

Open a GitHub issue (or PR with a draft RFC) titled `[SPEC] <one-line summary>`. The body has these sections:

### Motivation

What real-world annotation pattern is currently unliftable? Cite specific source-library annotations, specific kits that hit the wall, and the count of currently-skipped fixtures that this change would unblock.

Bad motivation: "this would be cool to have."
Good motivation: "the `pydantic` adapter currently skips 12% of `Field` constraints because the IR has no way to express temporal predicates. The Bean Validation adapter has the same gap. Adding `temporal_atomic` to the IR would unblock both adapters."

### Specification

The exact change to the spec, presented as a diff against the current spec bytes. Include:

- The spec file affected.
- The exact wording change.
- Worked examples showing canonical IR before and after.
- The downstream impact: which fixtures change, which kits need updates.

### Compatibility

Explicit statement of:

- What old `.proof` bundles look like under the new spec (typically: still valid).
- What old kits do when reading new `.proof` bundles (typically: skip new primitives with a warning).
- What old kits do when running on a new catalog (typically: fail `sugar verify-protocol` until upgraded).

### Alternatives considered

Alternatives you considered and rejected. "Why not just use a composition of existing primitives?" "Why not handle this at the adapter level?" "Why not defer until v2.0?" Each alternative gets a paragraph.

This section is where most ill-conceived proposals get filtered out. If you can't argue against a clean alternative, the proposal isn't ready.

### Adoption plan

Who is going to do the work? Concretely:

- Spec change.
- CDDL grammar update (if applicable).
- Codegen regeneration in every kit.
- Self-contracts re-mint in every kit.
- Fixture additions/updates.
- Lift adapter updates.
- Tutorial and reference doc updates.
- PEP transition body/witness under `protocol/evolution/<version>/` if the catalog changes.
- Proof-protocol/Bug Zoo vector updates if the new claim family affects `.proof` or realizer behavior.

Most spec proposals fail because they have no adoption plan. Whoever proposes a change generally takes responsibility for shepherding the change through. Maintainers can help, but you're driving.

## Review

The review process:

1. **Maintainers triage.** Within a week of posting, a maintainer responds with one of: "accepted, please open a PR," "needs more motivation, see comments," or "rejected, see reasons."
2. **Drafting.** If accepted in principle, the proposal moves to a draft RFC PR that lives in `docs/internal/rfcs/`. The PR contains the full spec diff plus all downstream changes.
3. **Implementation.** The PR makes the spec change, updates every kit's codegen and self-contracts, updates every fixture. The PR is large; split into reviewable commits.
4. **Conformance**. `make ci` passes. Every shipping kit re-mints successfully.
5. **Merge into a release branch.** Version class follows PEP. Extension-only catalog additions with no required kit emission, lift, canonicalization, or verifier changes may ship as patch-level transitions. Grammar changes, new core obligations, and required kit behavior changes generally wait for the next minor or major.

The review prioritizes:

- **Motivation strength.** Real pain, real coverage gap, real worked example.
- **Compatibility analysis.** No surprise regressions for old `.proof` bundles or old kits.
- **Adoption commitment.** Who's doing the work.
- **Lattice tractability impact.** Does the change make the lattice harder to reason about?

## Lattice tractability

The lattice tractability theorem (CID `blake3-512:b6d7c277...`) is the load-bearing property of the protocol's cost model. It says: honest verifier cost is a function of grammar parameters and decision-procedure complexity, not of the populated cardinality of the address space.

Some spec changes can break tractability:

- **Adding an IR primitive whose decision procedure is super-polynomial in the grammar size** would break Tier 3 cost characterization.
- **Adding a quantifier alternation that escapes the decidable fragment** would break Tier 3 entirely for affected formulas.

Proposals that touch the IR grammar must include a paragraph on tractability impact. "This addition stays within the EPR fragment," for instance, or "this introduces a new Σ₂ class but the kit emits only Π₁ instances."

If the proposal fundamentally breaks tractability, it is rejected. The protocol's cost model is structural; trading it away for adapter ergonomics is a bad deal.

## Backout

A spec change in flight can be backed out before the catalog bump ships. After the bump, backout is hard: every catalog transition, accepted CI witness, and kit attestation may have named the new catalog CID. Reverting the spec means another PEP transition and, if kit behavior changed, another conformance pass.

Maintainers prefer to discover problems before the bump. The pre-release checklist (in [release-process.md](release-process.md)) is the gate.

## When this is done

The spec change is in `protocol/specs/`, the CDDL grammar (if applicable) is updated, every kit re-mints, every fixture is updated, the catalog CID has bumped, and the new version has shipped per [release-process.md](release-process.md).

The change is now load-bearing. Future contributions can use the new primitive freely.

## Read next

- [release-process.md](release-process.md): how the bump itself happens.
- [docs/explanation/architecture.md](../explanation/architecture.md): the architecture the spec governs.
- `docs/reference/lattice-tractability.md` (planned): the tractability theorem.
