# Grouped Effects and `except*` Design

## Authority and representation

`GroupedRaiseEffect` is an immutable exception-group tree. Every group node retains its authenticated source occurrence identity, message value, and ordered children. Every leaf is the existing `RaiseEffect`, including its authenticated exception coordinate, MRO testimony, raised value, and occurrence identity. An empty subgroup is represented by the same group node with an empty `children` tuple; it is never host `None`.

`Raise` may construct this effect only when its callee has the authenticated builtin exception-group coordinate. Nested group and leaf children are constructed recursively through their ordinary typed Nodes and Sugars. Spelling does not grant group authority, and unsupported/dynamic children stay loud.

## Partition and routing

The shared `effect_router` performs one recursive partition. Each leaf asks the merged #6177 Python floor whether its authenticated raised type is a subtype of the authenticated handler type. The result produces two topology-preserving group trees: matched and residual. Neither face is omitted when empty.

`TryStarSugar` sends only the matched subgroup to its handler slot. The residual subgroup continues to the next handler. Handler-raised effects are retained. After all handlers, the router regroups handler-raised effects with the unmatched residual using group occurrence identities and original child order. A bare re-raise of the matched subgroup plus its complementary residual reconstructs the original tree; it never flattens or selects a leaf.

Ordinary `TrySugar` remains distinct and keeps first-total-match `except` semantics. `TryStarSugar` alone accepts grouped effects and partial partitions. Both use the shared ExitSet effect router and the existing in-flight effect slot.

## Loud boundaries

Dynamic exception-group constructors, missing leaf identity/MRO testimony, symbolic subtype partitions that cannot be represented as guarded group topology, and unsupported non-group effects reaching `except*` remain typed loud. No package, vendor, handler spelling, or observed execution grants authority.

## Acceptance

Tests cover nested topology, partial matching, residual-to-next-handler flow, handler bare re-raise, unmatched propagation, explicit empty faces, leaf occurrence preservation, renamed truthful/lying identity twins, and never-flatten/never-first-leaf discrimination. Permanent construction side-door and panic-catch laws remain zero.
