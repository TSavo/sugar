# Construction-Occurrence Object Identity Design

## Scope

Lane 4 adds the general object-identity substrate needed by calls, methods,
loop state, and external pandas/NumPy attribute fields. This slice implements
only attribute places (`obj.field`). Subscript places (`obj[key]`) remain
typed-loud and are the next slice; attribute identity does not wait on them.

This rebuilds the useful immutable-field ideas from draft PR #6126 on current
`main` without merging or copying its binding-owner or plain-class admission
model.

## Identity authority

Identity comes only from a construction occurrence. `ObjectCoordinateV1` is a
closed, content-addressed coordinate with two authenticated variants:

- A source-constructed coordinate commits to the allocation definition, exact
  call occurrence, construction-context generation, source CID, and artifact
  CID.
- An opaque-result coordinate commits to the exact native/opaque call
  occurrence, construction-context generation, source CID, and artifact CID.

The coordinate law is `h = h(p)`: the CID is recomputed from the complete
preimage. Different call occurrences have different coordinates even when
their spelling, callee, type, arguments, or resulting contents are equal.
Neither a `BindingEntryV1` coordinate nor a class/name/vendor test may mint or
admit object identity.

An opaque-result coordinate proves identity and aliasing only. It carries no
invented field, descriptor, behavior, return-type, or class testimony.

## Sole temporal path and aliasing

An object-bearing constructed node carries its authenticated object coordinate
and immutable field-state projection through the existing runtime
`BindingEntryV1.state`. The binding entry remains the one temporal carrier but
is not the source of object identity.

Ordinary assignment copies the constructed object coordinate unchanged.
Aliases therefore share one identity. A distinct call construction mints a
distinct coordinate. There is no ambient heap, secondary name map,
compatibility decoder, spelling gate, or class-specific pandas/NumPy arm.

Branch joins use the existing guarded binding faces. A field version available
on one completion face stays guarded on that face. Halted faces publish no
later mutation.

## Attribute places and immutable versions

`AttributeFieldCoordinateV1` content-addresses an authenticated attribute
selector. Field state is keyed by the typed pair
`(ObjectCoordinateV1, AttributeFieldCoordinateV1)`.

Every authenticated attribute store creates a new immutable
`AttributeFieldVersionV1`. Its preimage commits to the object coordinate, field
coordinate, exact store occurrence, constructed stored-value testimony,
construction generation, and optional prior-version CID. A read projects only
the latest authenticated version for that pair. Earlier projections retain
their earlier version, and independent object/version chains cannot cross.

Decode and projection recompute every coordinate and version CID. Any forged
identity, selector, prior link, stored value, or version CID is rejected with a
typed construction/provenance gap.

## Behavior authority and loud boundaries

An attribute store/read is constructible only when source construction proves
the applicable allocation, attribute lookup, descriptor, and `__setattr__`
behavior. Custom allocation, data descriptors, custom `__getattribute__`,
custom `__getattr__`, custom `__setattr__`, monkey-patched behavior, and absent
source testimony remain typed-loud.

An opaque call invalidates only field knowledge for authenticated object
coordinates that may be reached by that call and for which no frame testimony
proves preservation. Unrelated object coordinates and fields remain intact.
An unknown alias escape that prevents a sound affected-set construction stays
typed-loud; it does not silently preserve knowledge or clear an invented global
heap.

Opaque/native results receive authenticated opaque-occurrence identity with an
empty field-state projection. Aliasing that result copies its coordinate, but
field reads and behavior remain typed-loud until separately constructed.

All subscript reads and stores remain typed-loud in this slice.

## Construction flow

1. Construct the call occurrence exactly once through the sole call path.
2. When allocation definition testimony exists, mint a source-constructed
   object coordinate from that definition and occurrence. Otherwise mint an
   opaque-result coordinate from the authenticated call occurrence.
3. Carry that coordinate in the constructed result through ordinary temporal
   assignment and substitution.
4. For an attribute store, authenticate object and behavior testimony, construct
   the RHS exactly once, and append an immutable field version.
5. For an attribute read, validate the coordinate and complete version chain,
   then project the stored constructed value.
6. At opaque calls, construct the reachable affected set or remain typed-loud;
   invalidate only that set.

## Acceptance and instrumentation

The focused acceptance instrument has truthful, lying, and renamed structural
twins for:

- store then read;
- distinct construction occurrences do not collide;
- aliases share one identity;
- store, read, re-alias, mutate, and read again preserves immutable versions;
- distinct version chains do not cross;
- opaque calls invalidate affected field knowledge only;
- forged identities and versions are rejected;
- opaque/native results receive opaque-occurrence identity without fields;
- unknown alias escape stays typed-loud; and
- subscript places stay typed-loud.

The fixtures and structural auditor forbid identity based on name, type,
spelling, equality, field contents, vendor, and `BindingEntryV1` ownership. A
construction side-door instrument reports every live offender and replacement
shape, including new name/class/vendor dispatch, ambient identity tables,
generic fallbacks, panic catches, and subscript fabrication. It stays red while
any stable-zero term is nonzero.

The pandas measurement reports a proven non-empty base/head denominator and
numeric outcome transitions. Honest `Delta R` is read only from those receipts;
a completed process, focused green tests, or missing output is not a measured
delta.

## Floors

- One temporal binding model and one construction path.
- `h = h(p)` for every coordinate and immutable version.
- No name, type, spelling, equality, field-content, or vendor identity gate.
- No fabricated fields, behavior, aliases, coordinates, versions, CIDs, or
  signatures.
- Zero new construction side-door findings.
- Zero panic catches.
- No timeout increase in the battleaxe measurement.
- Heavy validation and pandas measurement run only on battleaxe.
- Rebase on current `origin/main` immediately before final review and push.
- Open the PR for user review and do not self-merge.
