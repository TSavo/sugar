# Pin all the things, witness all the outputs — toolchain rendezvous pinning (M4)

**Status:** design note. Realizes M4 ("pin every vector, name every IO"). 2026-06-20.

## Trigger

PR #2289 ("component rendezvous planning") gave the CLI **zero-config** discovery:
it owns generic composition, while each component answers over RPC
(`sugar.component.plan`) — *"does this workspace look like mine, and what
surfaces/manifests do I contribute?"* That is a large UX win and the correct
federation primitive (language-blind core, components own their semantics). It
also introduces a **new trust surface**: the CLI now trusts a component's *claim*
to a workspace and the *manifest it hands back*. #760's `PluginRegistryMemento`
pins which plugins ran — the **output** of planning — but not *why* they were
chosen. A wrong-or-malicious component that mis-claims a workspace and returns a
plausible manifest is pinned-but-unaudited.

*Supra omnia, rectum.* A planner you must trust is a vendor (the next xz). We add
recomputation, not trust — including over our own toolchain.

## Frame

The rendezvous is itself a derivation, and gets the same `k(I)=t` treatment as a
correctness proof, one level up:

```
workspace ──census──▶ CENSUS ──plan_fn(census, components)──▶ RESOLVED PLAN ──run──▶ ARTIFACTS
   I₀                  (I)             (k = the deciders)         (t)              (proof members)
```

Self-application: **sugar pins and witnesses its own toolchain** exactly as it
pins and witnesses a lift. Two moves — *pin all the things as mementos, then
witness all the outputs as witnesses* — and a contract/discharge pair falls out.

## Part 1 — the plan, pinned (the sworn statement)

A `PlanMemento` is a CID over the **derivation**, not just the result:

- `census_cid` — workspace evidence (a pure function of the tree).
- `[component_cid]` — each component's identity, **including its binary CID**.
- `[claim]` — each `H(component_cid, census_cid, response)` ("this workspace is
  mine, here is my `PlannedLiftManifest`").
- `[resolved_command]` — the rendezvous output.
- **expected output CIDs** — what the planner commits the run will produce.

`plan_cid = H(census ‖ components ‖ claims ‖ resolved ‖ expected)`. Re-walkable:
re-run `plan_fn(census, components)` → same `plan_cid`. The *why-this-kit* is now
auditable, not just the *what-ran*. #760's `PluginRegistryMemento` becomes a
**derived view** of the plan.

## Part 2 — the run, witnessed (the recomputation)

The run is recorded with the system's **existing** witness mechanism — signed
`WitnessMemento`s in a `.witness` bundle, the same infra that witnesses
cargo-test / correctness claims, now turned on the toolchain run itself
(self-application; no new memento type). One signed `WitnessMemento` per
invocation carries the triple that makes re-execution possible —
*derivation-possession, not the recorded artifact*:

```
witness_i = ( binary_cid_i , input_cid_i , actual_output_cid_i )   # signed
```

Signed ≠ trusted: the signature makes provenance accountable, but the witness's
worth is still its re-runnability (recompute the binary on the input, check the
CID), never its assertion. The `.proof` holds the pinned, *declared* plan; the
`.witness` bundle holds the signed, *empirical* record that the plan ran and
produced these.

## Discharge

```
discharge ≡  plan.expected_output_cids  ==  witness.actual_output_cids   (memcmp(64))
```

The **plan is the gate; the run is the producer.** Equal → the toolchain ran
exactly as declared (confirmed). Unequal → refuted: drift, tamper, or
nondeterminism. Plan-without-witness = declared-but-unconfirmed; witness-without-
plan = ran-but-unaccountable; together = a closed, totally-accounted toolchain
derivation. Maps to the promotion tiers: the plan in `.proof` = *declared*; the
signed witness in the `.witness` bundle = *empirically-witnessed*.

## Invariants

1. **Determinism is a contract, not a hope.** `plan_fn` and every component must
   be pure functions of their input. A nondeterministic component is **refused**
   (or pins its seed) — otherwise the chain is not re-walkable. Same rule that
   bans `Date.now()`/`random` from a resumable workflow.
2. **The planner pins itself.** `plan_fn` is sugar's own code; the sugar **binary
   CID** is part of the pinned `k`. Self-application — sugar proves sugar — fine
   as long as it is *named*, not hidden.
3. **Name the TCB; terminate the regress there.** Re-walking bottoms out at
   `{blake3, OS exec, the structural floor}`. Everything above is recomputed; the
   floor is the declared TCB.
4. **The silence gets a CID.** "No component claimed this workspace" (the
   `apt install sugar-kit-rust` path) is a pinned *negative* (census + empty claim
   set), not an untracked gap. Unentered ≠ empty.
5. **Storage is invariant.** Inline-in-envelope vs reference-by-CID-into-a-store
   is only *where the bytes live*; soundness depends solely on the recomputable
   CID-chain being in the `.proof`.

## Concrete delta

The machinery already exists — M4 is **wiring, not invention**: the pin side is
the memento-sealing (`PluginRegistryMemento`/#760); the witness side is `.witness`
bundles + signed `WitnessMemento`s.

- Seal `ComponentPlan` → `PlanMemento` in the `.proof` (census + component-CIDs +
  claims + resolved commands + expected output CIDs).
- Emit a signed `WitnessMemento` into the `.witness` bundle per toolchain
  invocation (binary_cid, input_cid, actual output_cid) — the existing witness
  infra, applied to the toolchain.
- `PluginRegistryMemento` (#760) becomes a derived view of the plan.
- Discharge by `memcmp(plan.expected, witness.actual)`.

Same move as the 2026-06-20 forall-rewrite (pin the premise, recompute the result,
let equality be the certificate) — one level up, on the toolchain itself.
