# Temporal Successor S1 Diagnosis (#3445)

This slice is diagnosis only. It names the three machinery gaps behind the
temporal successor work without changing production code.

## Read Receipts

- Issue #3445: diagnosis-first over symbolic-variant guards, confirm-side
  Derived universe, and family-j.
- PR #3443: temporal close, including S7 receipts that
  `constraint_literal_iterator_quantifier` remains a temporal successor because
  the lying `.all()` row still SATs even with per-element facts counted.
- PR #3432: grounded concrete Option/Result form. Concrete grounded variants
  lift; symbolic variants refuse.
- PR #3367: ambient replay is keyed by `(semantic_cid, provenance_kind)` for
  ground callsite facts.
- DoR clause 7b: branch facts are emitted as guarded regions, then joined by
  guard implications.

## Diagnosis 1: Symbolic Variant Guards

Gap name: `symbolic-monadic-variant-region`.

Current seat:

- `implementations/rust/sugar-lift-rust-tests/src/sugar/option_adaptor.rs:650`
  reduces the receiver to a `Term` and dispatches only through
  `option_payload` / `result_payload`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/option_adaptor.rs:1175`
  prepares Option payloads by converting the payload to a `ConstVal`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/option_adaptor.rs:1275`
  refuses any non-ground payload with `Effect::RuntimeMonadicPayload`.

What happens today:

`Some(x).map(...)` or `Some(x).and_then(...)`, when `x` is symbolic, reaches
`OptionAdaptorSugar`. The carrier is recognized as Option/Result, but the
payload must pass `ensure_grounded_payload`; a non-literal payload produces
`RuntimeMonadicPayload` instead of a guarded Some/None split.

The branch machinery that already realizes DoR 7b is statement-shaped:

- `implementations/rust/sugar-lift-rust-tests/src/sugar/if_sugar.rs:90`
  lifts an `if` condition into a `Formula`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/if_sugar.rs:111`
  prefixes the then branch with `cond`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/if_sugar.rs:141`
  prefixes the else branch with `not(cond)`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/control_flow_guard_operation.rs:25`
  is explicitly a closed visitor over statement exits.

Needed carrier:

A symbolic monadic variant needs a value-level carrier, not just another
statement guard helper. The smallest shape is a closed carrier such as
`MonadicVariantRegion`:

- carrier: Option or Result;
- alternatives: Some/None or Ok/Err;
- guard formula per alternative;
- payload binding and payload term/sort when that alternative carries a value;
- region output term for the combinator callback.

The emission law then lowers the carrier as guarded value regions:

- Some/Ok path emits `variant_guard -> result == callback(payload)`;
- None/Err path emits `variant_guard -> result == default/original error`;
- joins are implications, mirroring DoR 7b for branch exits.

Classification:

This is both a floor-value gap and an emission-shape gap. The floor cannot
represent a symbolic sum standing today, and the emitter has no value-region
analogue of `ControlFlowGuardOperation`. Size: small closed carrier plus a
medium emission law. Sequence: build before enrolling symbolic Option/Result
map/and_then rows.

## Diagnosis 2: Confirm-Side Derived Universe

Gap name: `derived-universe-member-emission`.

Current seats:

- `implementations/rust/sugar-verifier/src/consistency.rs:101` defines typed
  `ProofIrProvenanceKind`.
- `implementations/rust/sugar-verifier/src/consistency.rs:1395` defines
  `AmbientGroundCallsiteFact` with an `AmbientFactWitnessKey`.
- `implementations/rust/sugar-verifier/src/consistency.rs:1412` collects ground
  callsite facts with provenance kind.
- `implementations/rust/sugar-verifier/src/consistency.rs:1847` conjoins
  ambient universals as raw `Json`.
- `implementations/rust/sugar-verifier/src/consistency.rs:2248` collects
  universals from candidate invs without a witness key.
- `implementations/rust/sugar-verifier/src/consistency.rs:2252` collects ground
  callsite facts with the candidate's provenance kind.
- `implementations/rust/sugar-cli/tests/cmd_verify_lifted_forall_universe.rs:340`
  is the smallest production failing attempt.

Production failing attempt:

Command:

```text
../../bin/bcargo test -p sugar-cli --test cmd_verify_lifted_forall_universe -- --nocapture
```

Receipt:

```text
NO UNIVERSE rows: [
  user_false g(3) refused,
  user_true g(4) refused,
  user_true panic refused,
  user_false panic refused
]
WITH UNIVERSE rows: [
  user_false g(3) unsatisfied,
  user_true g(4) refused,
  vendor_loop refused,
  user_true panic refused,
  user_false panic refused
]
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 9.70s
```

Interpretation:

The counted/lifted universe is real enough to refute the false unnamed point
claim `g(3)==2`: the solver instantiates the conjoined universal at an input
the assertion did not materialize. The matching true unnamed point claim
`g(4)==1` still refuses because the universe is not independent-kind testimony
for confirmation. The current law treats Stated-only confirmation as missing
an independent Derived witness.

Replay capability check:

A scratch verifier probe built the same shape with a Derived candidate carrying
`forall 0 <= x < 3 -> g(x) == 1` and a Stated point claim `g(2)==1`. That probe
discharged:

```text
test consistency::tests::diagnosis_derived_universe_confirms_true_unnamed_point_claim ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 250 filtered out; finished in 0.02s
```

The scratch probe was not committed. It shows the replay/solver side can
confirm a true point once a Derived universe is present. Therefore the primary
gap is emission-side: temporal counted facts that represent a discovered
universe are not minted as a Derived universe member.

Secondary replay cleanup:

Ground callsite facts already carry `(semantic_cid, provenance_kind)`, but
ambient universals still travel as raw JSON. The next build should consider a
typed `AmbientUniversalFact { formula, witness_key }` so the same-kind
independence law is explicit for universals too. This is not the blocking gap
for the production receipt above; the blocker is that no Derived universe member
is emitted.

Classification:

Primary: emission-side addition. Size: small typed member or memento addition
for Derived universe testimony, plus a narrow mint path from temporal counted
facts into that member. Replay-side universal witness typing is a small follow-up
or same-slice hardening if the builder chooses to close the kind gap there.
Sequence: build after the symbolic carrier if the source universe depends on
symbolic guards; otherwise this can proceed independently.

## Diagnosis 3: Family-J

Gap name: `literal-iterator-quantifier-derived-universe`.

Current seats:

- `implementations/rust/sugar-lift-rust-tests/src/sugar/literal_iterator_quantifier.rs:33`
  keeps `constraint_literal_iterator_quantifier` as the `#3415 successor /
  family j` temporal-campaign row.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/literal_iterator_quantifier.rs:101`
  curries the predicate once per finite literal element.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/literal_iterator_quantifier.rs:113`
  emits the joined atoms as one assertion-local `Desugared::Constraints`.
- `implementations/rust/sugar-lift-rust-tests/src/sugar/literal_iterator_quantifier.rs:147`
  creates occurrence-renamed per-element terms through `temporal_curry_occurrence`.
- `implementations/rust/sugar-lift-rust-tests/tests/sugar_witness_triple.rs:863`
  gates the row as a named temporal successor until the lying-SAT contradiction
  drains.

Receipt:

```text
S7 successor: constraint_literal_iterator_quantifier remains temporal-campaign row: #3415 successor / family j: finite literal iterator quantifier curry facts still lack lying-SAT contradiction
test s7_temporal_successors_are_named ... ok
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 21 filtered out; finished in 0.00s
```

Cross-chain answer:

Family-j should fall out of the confirm-side Derived universe work if the
per-element quantifier facts are emitted as Derived universe testimony instead
of only assertion-local constraints. The counted/curry substrate is already
present; what is missing is the promotion of those counted facts into the
independent-kind universe that can contradict or confirm sibling claims.

Do not start with a separate solver or verifier thread for family-j. First build
`derived-universe-member-emission`, then enroll the family-j pair. Only split a
new thread if the row still SATs after the per-element facts have a Derived
universe member and stable semantic CIDs.

Classification:

Small emission law gated by diagnosis 2. No new floor appears necessary from the
current trace. Contingent follow-up only if non-call predicate atoms cannot be
named with the existing semantic-CID vocabulary after Derived universe emission
lands.

## Sequencing Recommendation

1. Build `symbolic-monadic-variant-region`: a value-level Option/Result symbolic
   carrier plus guarded value-region emission. This unlocks symbolic variant
   guards and gives the 7b branch implication law a value counterpart.
2. Build `derived-universe-member-emission`: mint temporal counted universes as
   Derived testimony. Keep the existing fail-closed rule that Stated cannot
   confirm Stated; consider typing ambient universals with witness keys while in
   the verifier neighborhood.
3. Re-enroll family-j only after step 2. Expected result: the
   `constraint_literal_iterator_quantifier` lying twin becomes UNSAT via the
   Derived universe facts. If it remains SAT, split the remaining gap as a
   family-j-specific naming/semantic-CID issue.

## Final S1 Statement

No production code should change in this slice. The current machinery is
correct to refuse rather than fabricate Derived testimony. The successor work is
not "make the refusal go away"; it is to introduce the missing typed carriers
and Derived universe emission so the production pipeline can carry independent
testimony honestly.
