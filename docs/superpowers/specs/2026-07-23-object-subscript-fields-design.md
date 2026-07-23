# Object Subscript Field Coordinates

## Ruling

A supported `obj[key]` place is one field-coordinate variant inside the existing `ObjectPlaceStateV1` version map. Its owner is the construction-occurrence `object_coordinate`; its selector is an authenticated coordinate for the key's constructed value. It never derives object identity from a binding, type, spelling, equality, or field contents.

## Representation

Add `SubscriptFieldCoordinateV1(object_coordinate, key_coordinate, cid)` and `SubscriptFieldVersionV1` beside the attribute variants. The key coordinate cites a decoded `ConstructedValueTestimonyV1` and the constructed key term CID. `ObjectPlaceStateV1.selectors`, values, testimony, version, prior-version, and occurrence arrays remain the sole versioned field map. No generic-field rewrite and no second subscript state exist.

## Construction

`obj[key] = value` constructs the receiver, key, and value exactly once. When the receiver is an authenticated `ObjectPlaceStateV1`, the key has supported immutable/hashable construction testimony, and class subscript dispatch is default and constructed, it mints a subscript field version linked to the prior version for the same owner/key coordinate. `obj[key]` reconstructs the identical key coordinate and projects only the matching authenticated version.

Opaque receivers, symbolic or opaque keys, unhashable keys, custom `__getitem__`/`__setitem__`, out-of-range accesses, forged coordinates/versions, and unknown selector variants remain typed-loud. Opaque calls invalidate only exposed object field knowledge, using the existing invalidation path.

## Acceptance

Truthful/renamed and lying twins cover store/read by key, distinct keys, alias sharing, immutable mutate/read chains, distinct object chains, forgery rejection, selective invalidation, symbolic key loudness, custom dispatch loudness, unhashable/out-of-range loudness, and opaque receiver/key loudness. Attribute behavior and wire vocabulary remain unchanged.
