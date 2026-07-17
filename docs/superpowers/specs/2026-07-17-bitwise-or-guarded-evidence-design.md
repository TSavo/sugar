# Bitwise-Or Guarded Evidence Design

## Scope

Retire the verified-live `owner=bitwise_or observed=GuardedValue` terminal in
`pandas/tests/groupby/test_api.py` without translating missing construction
into a runtime effect.

## Construction

`SetValue.bitwise_or(SetValue)` constructs Python set union exactly: retain the
left operand's construction order and append right-hand elements not already
present. `GuardedValue.bitwise_or` distributes the operation through both
faces using the existing guarded `_map` join, preserving the branch guard and
the exact face values.

No `RuntimeEffect` is added. Both the receiver faces and the right operand are
available at lift time. Perfect machinery can decide the result, so an effect
would be dishonest. Non-set operands and unsupported guarded faces continue to
raise the existing loud `owner=bitwise_or` `FactoryPanic`.

## Evidence

Focused tests prove:

- exact set union constructs a `SetValue`;
- guarded set union constructs a `GuardedValue` with the same guard and exact
  union on each face;
- a concrete unsupported operand remains `FactoryPanic owner=bitwise_or`;
- `GuardedValue` declares the new operation explicitly.

The bounded pandas replay must move the one named representative away from
`owner=bitwise_or`, while any next independent frontier remains loud. The
receipt accounts for completed, advanced, effect, and silent mass; silent must
remain zero.

