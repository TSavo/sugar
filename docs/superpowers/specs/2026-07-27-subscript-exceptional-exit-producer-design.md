# Subscript Exceptional-Exit Producer Design

## Goal

Make the general Subscript floor emit authenticated exceptional exits exactly
when source-visible receiver semantics decide them.  The concrete witness is
`pandas/tests/test_multilevel.py:157` from pandas 3.0.3:

```python
with pytest.raises(KeyError, match=r"^\(\('foo', 'bar', 0\), 2\)$"):
    series[("foo", "bar", 0), 2]
```

The assertion manager is outside this design.  It consumes halted ExitSet
edges and never locates or interprets the expression that produced them.

## Ownership and data flow

`SubscriptSugar` sequences receiver and index construction and delegates to the
receiver's existing Subscript floor.  Receiver floors own all decisions:

- A concrete, source-visible container returns its exact stored value when the
  key or index succeeds.
- A concrete container emits a `RaiseEffect` with authenticated native type
  testimony when its own semantics prove a missing key or invalid index.
- An opaque, symbolic, custom-dispatch, or otherwise undecidable receiver/key
  produces a named construction refusal.  It does not return a completed
  `py.subscript` coordinate and does not guess `KeyError`, `IndexError`, or a
  generic runtime effect.

No assertion-With, ExitSet algebra, outcome, or generator file participates.
Existing occurrence-authenticated subscript field coordinates remain the sole
temporal identity mechanism; this change adds no parallel heap or selector.

## Authentication boundary

Exceptional exits use the receiver floor's native testimony.  Built-in literal
container semantics may authenticate their language-defined exception class;
vendor objects and operands without a decidable source-visible type may not.
Partial knowledge remains undecidable: absence of one provable success is not
proof of a particular failure.

## Tests and mutation gate

The authenticated pandas 3.0.3 site establishes the initial boundary.  Focused
twins then pin both sides of the producer law:

1. Truthful: a concrete missing-key or invalid-index lookup emits one halted
   authenticated exceptional exit.
2. Lying: a successful concrete lookup must not emit that exceptional exit.
3. Undecided: the real symbolic pandas receiver remains a named refusal unless
   its source-visible type becomes authenticated; it is never interpreted as
   false or as a guessed exception.

After green, revert the production law in a clean tree, prove the focused test
fails for the intended missing exceptional edge, restore it, rerun green, and
verify the tree is clean.  Run focused modules for every modified Python
package through the repo-relative authenticated launcher.  Preserve zero
construction panics, timeouts, native crashes, and unaccounted outcomes.

