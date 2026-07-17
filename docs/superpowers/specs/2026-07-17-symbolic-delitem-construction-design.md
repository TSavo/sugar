# Symbolic Delitem Construction Design

## Live frontier

Current main (`0d7d85237`) fails loudly at
`numpy/f2py/symbolic.py:146:12`:

```
owner=delitem
observed=SymbolicValue
requested=stand on the subscript-delete floor
```

The deleted receiver is the formal mapping `d` in `_pairs_add`. Its element
history is unavailable while independently reducing the function, but its
post-state is constructible as the same `py.delitem(receiver, index)`
coordinate already used by `CallSiteValue.delitem`. This is absent machinery,
not genuine runtime undecidability, so a RuntimeEffect arm would be unlawful.

## Design

Add `SymbolicValue.delitem` beside its existing `setitem` implementation. It
projects the receiver and index to ProofIR terms and returns a name-rebindable
`CallSiteValue` whose coordinate is `py.delitem`. No members or mutation result
are invented.

Also construct the fully ground mapping arm in `DictValue.delitem`: a concrete
key removes the matching entry; a concrete missing key retains the existing
honest `KeyErrorRuntimeEffect`; a non-ground key retains a genuine
runtime-dependent `SubscriptStoreRuntimeEffect` through the existing evidence
door. Ground non-container receivers continue to panic via `FloorValue`.

Alternatives rejected:

- Relabel `SymbolicValue` deletion as a RuntimeEffect: perfect machinery can
  construct the post-state coordinate, so this would suppress an unimplemented
  floor.
- Leave the current panic: preserves loudness but does not construct the live
  decidable frontier.
- Inspect the NumPy helper syntax: couples the floor to one vendor spelling
  instead of owning the semantic receiver/index operation.

## Evidence

- A focused symbolic discrimination test requires a `py.delitem` rebind.
- A concrete dict deletion test proves ground post-state construction.
- A ground non-container bad twin remains `FactoryPanic`.
- A new verdict-bearing dict-delete witness has truthful `sat` and lying
  `unsat` arms.
- Bounded replay moves the representative from `owner=delitem` to completion
  or a distinct loud named owner, with silent zero.
- The concrete-dict floor's non-ground key is a genuine runtime operand through
  the existing evidence door; its ground missing-key wrong twin must refute via
  `FactoryPanic`, and the RuntimeEffect constructor census must remain at zero
  failures.
