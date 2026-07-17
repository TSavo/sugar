# Subscript floor evidence design

## Scope

Issue #4709 measures 18 assertion-bearing corpus files whose first terminal
construction is the legacy `subscript` floor.  Current-main reproduction found
two live receiver shapes: `PredicateValue` and `ComprehensionValue`.

## Soundness boundary

`ComprehensionValue` denotes a real Python collection construction, but a
runtime iterable prevents lift-time knowledge of its members and cardinality.
Subscript therefore preserves the lookup as the existing proof-bearing
`py.subscript(receiver, index)` callsite coordinate.  It does not invent an
element or claim that lookup cannot raise.

`PredicateValue` carries only a formula.  It does not carry enough Python
type/shape evidence to distinguish a scalar boolean (not subscriptable) from a
runtime array of booleans (subscriptable).  That operation remains red as a
named `SubscriptResultRuntimeEffect`, authenticated by the predicate term and
source location.  It must not be lowered to a successful element lookup.

## Discrimination

- Runtime comprehensions retain an explicit `py.subscript` callsite.
- Predicate subscripts produce the named effect with a mandatory witness.
- Existing concrete list subscript evidence still proves the truthful
  `SubscriptSugar` witness and refutes its wrong twin.
- Concrete out-of-range and missing-key cases retain their typed effects.

Focused corpus children must advance past `owner=subscript`; any later owner is
reported as a distinct residual rather than absorbed by this change.
