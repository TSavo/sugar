# LoopConstructionV1 wire design

## Authority and hashing

Every record below is a canonical JSON object encoded through the repository's
existing RFC 8785 JCS encoder and addressed with BLAKE3-512. A record CID is
`blake3-512(JCS(preimage))`. The preimage contains every semantic field and
never contains the record's own CID. Decoders require an exact key set,
recompute the CID, and reject stale children before admitting their parent.

CID strings are references only. A reference is usable when the referenced
record is present in the same sealed graph and independently validates. There
is no string/name lookup and no alternate loop authority.

## BindingStateV1

`BindingStateV1` is a sorted snapshot of binding-coordinate cells:

```json
{
  "kind": "binding-state",
  "schemaVersion": "1",
  "entries": [
    {"bindingCoordinateCid": "CID", "cell": "BindingCellV1"}
  ],
  "stateCid": "CID"
}
```

Entries are strictly ascending by `bindingCoordinateCid`; duplicates and
unsorted states are malformed. A binding coordinate is minted by the existing
source/construction authority and is not an identifier spelling.

`BindingCellV1` is a closed tagged union:

- `BoundValue`: `{kind:"bound-value", valueConstructionCid}`. The referenced
  CID is the constructed value testimony, not source text or a variable name.
- `Unbound`: `{kind:"unbound", causeFragmentCid}`.
- `Guarded`: `{kind:"guarded", guardFormulaCid, whenTrueStateCid,
  whenFalseStateCid}`. Both referenced states must be in the sealed graph.

The state CID preimage is the object without `stateCid`. This makes state
identity a function of constructed cells, including guarded availability.
Missing constructed-value testimony is a typed construction gap; callers may
not replace it with a source fragment, name, `None`, or prose.

## Loop target and transforms

`LoopTargetCoordinateV1` preimage:

```json
{"kind":"python-loop-target","schemaVersion":"1",
 "loopKind":"For|AsyncFor|While","sourceFragment":{...}}
```

`targetCid` is the hash of that object. The CID is not included in its preimage.

Binder/body/test transforms are sealed testimony, not executable callbacks:

- `LoopBinderTransformV1`: target CID, input state CID, element-value CID,
  output state CID, and binder-pattern construction CID.
- `LoopBodyTransformV1`: target CID, input state CID, binder-transform CID or
  `null` for `While`, body source-fragment CID, and body-exit-template CID.
- `LoopTestTransformV1`: target CID, input state CID, test-value construction
  CID, true-guard CID, false-guard CID, and ordered halted-face CIDs.
- `LoopIteratorTestimonyV1`: target CID, iterable-value construction CID,
  iterator-construction CID, next-operation CID, and exhaustion-operation CID.

Each transform has a terminal `*Cid` field computed from all preceding fields.
The referenced states, faces, and child transforms must validate before the
transform is admitted. An unavailable child leaves the loop typed-loud.

## Exit faces and obligations

Completed faces are closed by `completionKind`:
`NormalExhaustion` or `BreakExit`. Their preimage is
`{kind,schemaVersion,targetCid,completionKind,guardFormulaCid,stateCid}`;
`completedFaceCid` is its hash.

Outward halted faces carry `effectCid`, `guardFormulaCid`, and `stateCid`; they
never reinterpret nonmatching loop effects.

Obligations are closed records:

- `LoopLatchObligationV1`: target, input completed-face CID, operation kind
  (`ForNext` or `WhileTest`), successor-transform CID, and exact input state.
- `LoopBreakExitObligationV1`: target, matching break-effect CID, input halted
  face CID, and output `BreakExit` completed-face CID.
- `LoopExhaustionExitObligationV1`: target, operation testimony CID, input state
  CID, and output `NormalExhaustion` completed-face CID.
- `LoopPostBindingV1`: target, binding-coordinate CID, incoming state CID,
  completed-face CID, and projected state CID. It is a projection obligation;
  it does not carry or synthesize a value.

Every obligation's own CID is the hash of the record without that CID.

## LoopConstructionV1

The closed top-level record contains the target, pre-state, exactly one
operation (`ForOperationV1` or `WhileOperationV1`), body transform, ordered
latch/break obligations, one exhaustion obligation, `elseBodyCid` or `null`,
ordered completed/outward-halted face CIDs, and ordered post-binding obligation
CIDs. `loopConstructionCid` hashes the complete object without itself.

`ForOperationV1` references a binder transform and iterator testimony.
`WhileOperationV1` references a test transform. Both carry the native
opaque-loop term CID for `python:for` or `python:while`; this report surrounds
that occurrence and does not claim a solved fixed point.

Final validation requires a closed reachable graph: all CIDs recompute, every
face targets the same loop, every matching continue feeds a latch, every
matching break maps to `BreakExit`, and only `NormalExhaustion` is sequenced
through `elseBodyCid`. Unknown tags, unknown fields, stale CIDs, missing graph
members, or malformed latches are typed-loud.

## Construction boundary

Concrete authenticated finite transitions may execute the ExitSet iteration
route exactly. Symbolic loops publish the native opaque occurrence plus this
closed obligation graph only when every referenced state and transform can be
sealed. Otherwise they remain typed-loud. `ForUniversalSugar` remains restricted
to fact-only, state-free, early-exit-free loops.
