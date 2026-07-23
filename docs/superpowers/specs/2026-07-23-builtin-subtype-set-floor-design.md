# Builtin Subtype and Finite-Set Python Floor Design

## Ruling

Python builtins gain meaning through closed operations on the Python floor. No
operation may be admitted by package name, leaf spelling, or an observed native
Boolean. The floor must authenticate the Python-runtime builtin identity, the
semantic operation, every operand, and the constructed result.

The lane owns these operations:

- `issubclass(T, U)` over authenticated class coordinates and their constructed
  base/MRO graph;
- tuple-of-types as a finite disjunction over the same subtype relation;
- membership, union, intersection, and difference over constructed finite set
  members;
- typed subtype or membership obligations when the relation is symbolic but
  the operands and operation remain authenticated.

Opaque or unsupported native behavior stays loud. In particular, this lane
does not add a generic witness that says an opaque builtin returned true.

## Architecture

The existing floor dispatch remains the sole construction path. An authenticated
builtin callable coordinate dispatches `issubclass` to the already-constructed
class/type operand rather than recognizing the source name. `ClassValue`
traverses only its authenticated base values. `TupleValue` performs a finite
left-to-right disjunction by invoking the same subtype operation for each arm.

Constructed `SetValue` owns membership and the three binary set operations.
Ground members are compared only through existing constructed equality or
identity testimony. When a relation cannot close but both operands have lawful
terms, the floor constructs a typed predicate/obligation naming the precise
subtype or membership operation. It never guesses a Boolean or uses Python host
object equality as semantic authority.

The operation witness is a closed testimony value containing:

- the authenticated Python runtime identity;
- an operation tag (`python.issubclass`, `python.set.contains`,
  `python.set.union`, `python.set.intersection`, or `python.set.difference`);
- operand term content identities;
- the result term or predicate content identity.

Verification must reject a witness when any operand, result, runtime identity,
or operation tag is altered.

## Manager Derivation

Installed-source manager construction continues to interpret source-visible
`__exit__` bodies. A body using authenticated `builtins.issubclass` reaches the
new floor operation. The resulting predicate feeds the existing
`EffectBoundarySemanticsV1` derivation. `pytest.raises` and
`contextlib.suppress` therefore derive through the same installed-source body
path. There is no package, exported-symbol, or manager-name branch.

## Loud Boundaries

The following remain typed loud outcomes:

- a shadowed or otherwise unauthenticated `issubclass` callable;
- a non-type tuple arm;
- dynamic native classes without authenticated subtype testimony;
- sets whose members cannot be constructed or whose equality relation is
  unsupported;
- native mutation or iteration-order behavior outside the four closed set
  operations;
- malformed, mismatched, or lying operation witnesses.

## Executable Instrument

The lane adds or extends an automated instrument that reports current `R` for:

- construction side doors around floor callable dispatch;
- package/name gates for `pytest.raises` or `contextlib.suppress`;
- generic opaque-builtin-result witnesses;
- panic catches introduced on the construction path;
- missing acceptance twins for subtype, tuple partition, finite-set, symbolic,
  opaque/native, and installed-source manager cases.

The instrument names the floor replacement shape for each finding and stays red
while any stable-zero term is nonzero. `Delta R` is read from base/head runs;
there is no checked-in threshold.

## Acceptance Evidence

Renamed, truthful, and lying twins must demonstrate:

- a matching subclass effect is consumed;
- a wrong type propagates;
- an absent effect fails;
- tuple-of-types partitions correctly;
- finite-set membership and the three finite set operations are decided;
- symbolic subtype and set relations produce typed obligations and remain loud
  to any consumer requiring a concrete Boolean;
- opaque/native cases remain loud;
- real installed-source `pytest.raises` and `contextlib.suppress` derive
  `EffectBoundarySemanticsV1` through this floor mechanism without a name gate;
- witness mutations to operands, result, runtime identity, or operation fail.

## Invariants

- One construction path; no compatibility or manager-specific evaluator.
- `h = h(p)`: constructed results depend only on authenticated construction
  inputs and semantic operation.
- No vendor arm and no package/name recognition.
- No fabricated result.
- Zero new construction-side-door findings.
- Zero panic catches.
- No timeout increase in the measured battleaxe receipt.
- Heavy validation runs only on battleaxe.
- Rebase onto refreshed `origin/main` before requesting review.
- Push an open review PR and do not self-merge.
