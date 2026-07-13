# Term Subterm Sharing Design

## Scope

Hash-cons Python-kit IR terms during one `lift_file_payload(source, filename)`
request. Structurally equal terms constructed during that request have one object
identity. The table is discarded when the request returns, including exceptional
returns, so separate lifts do not retain or share identity.

This change does not introduce a DAG wire format. Existing recursive serialization
continues to expand every occurrence, preserving canonical JSON, CIDs, and emitted
bytes.

## Construction boundary

`sugar_lift_py_tests.ir` owns the term variants and their constructors. Add a
request-scoped intern-table context there and route every term constructor through
one canonicalization helper. The existing frozen dataclass value is the structural
key. `_Ctor.args` remains a tuple, so an interned node and its descendants are
immutable and hashable.

Wrap the complete body of `lift_file_payload` in that context. Nested construction
therefore sees one table across all contracts produced from the source file. A
context-local binding prevents concurrent or nested lift requests from coupling
their tables. Calling constructors outside a lift remains valid and does not create
process-global retention.

Internal rewrites that currently instantiate term dataclasses directly must return
through the same constructors, or they would evade the one construction boundary.

## Soundness rails

- Preserve the current frozen term dataclasses and tuple children. Any attempted
  mutation continues to fail loudly.
- Preserve dataclass structural equality and hashing. The only newly observable
  property is that equal terms inside one lift may also satisfy `is`.
- Do not memoize, alter, or DAG-encode serialization. Compare canonical serialized
  bytes from an explicitly unshared term tree with bytes from the shared graph.
- Do not share objects between separate `lift_file_payload` calls.
- Do not change formula identity or representation unless term construction proves
  it is required for the reported construction blowup.

## Instrument and tests

Add a focused regression that constructs the nested-guard distribution shape through
the real lift boundary and measures repeated structurally equal term occurrences.
It must report current repeated-node offenders, fail while equal occurrences have
different identities, and name request-scoped hash-consing as the replacement. Pin:

1. repeated nested subterms are the same object by `id()`/`is`;
2. canonical serialization is byte-identical to an independently built unshared
   tree;
3. two lift requests do not share identities;
4. term mutation raises rather than silently corrupting the intern key.

Run the focused test as the code receipt. The real `/tmp/datetime-read` lift is the
performance receipt, measured before and after with wall-clock time and peak RSS.
It is not added as a CI gate.

## Predicted movement

Current `R` is the number of structurally equal term occurrences in the focused
nested-guard fixture that do not share identity. Predicted `Epsilon R` is all such
offenders in that fixture moving to zero, with serialization bytes unchanged and
cross-lift shared identities remaining zero.
