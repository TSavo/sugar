# GeneratorConstructionV1 Suspended-Machine Design

## Ruling

A Python generator is a suspended control machine, not an eager function
return. The lift has one generator construction path and derives generator
context-manager behavior mechanically from that construction. No decorator,
module, function, manager, or warning name grants generator or context-manager
semantics.

## Construction

`GeneratorConstructionV1` is the sole construction artifact for a generator
call. Allocation creates one stable instance coordinate and records the
suspended frame, its binding state, and its current resume coordinate. Calling
the generator function returns that instance construction without reducing the
body as an eager function body.

The suspended machine exposes four transitions: resume, send, throw, and close.
Each transition consumes the current resume coordinate and returns an
exhaustive typed result:

- `YieldEffect(value, resume_coordinate)` suspends with the exact constructed
  yielded value and successor coordinate;
- termination carries the generator return/termination face;
- halted body faces propagate with their guards and binding state intact;
- a transition the construction cannot prove becomes a typed loud residual.

No transition performs a second source evaluation or switches on `ast.*`.
Coordinates and transition terms are derived from source-authenticated
construction, so `h = h(p)` and renamed definitions construct identically.

## Mechanical Context-Manager Derivation

A `with` manager whose constructed value is a `GeneratorConstructionV1`
instance is routed by the following mechanics:

1. `__enter__` resumes the instance once. The first `YieldEffect` supplies the
   entered value and therefore the `as` binding.
2. Normal `__exit__` resumes from that yield and requires termination.
3. Exceptional `__exit__` throws the incoming effect into the suspended frame.
   Every completed and halted result remains in the resulting `ExitSet`; both
   suppression and propagation faces are preserved when guarded.
4. A second yield during exit, termination before the first yield, or an opaque
   transition remains typed and loud.

This is a construction consumer, not a context-manager recognizer. A renamed
generator manager behaves identically because no `contextlib`, `warning`,
decorator, or callable name is inspected.

## Instrument and Acceptance Evidence

Before implementation, an automated instrument discovers every current
generator-construction residual and forbidden side door, reports the current
non-empty denominator and `R`, stays red while stable-zero terms are nonzero,
and names `GeneratorConstructionV1` as the replacement shape.

Focused truthful and lying twins cover:

- renamed generator allocation and first-yield `as` binding;
- normal exit requiring termination;
- exceptional exit throwing the original effect and retaining both `ExitSet`
  faces;
- two yields, premature return, and opaque transition staying typed-loud;
- resume, send, throw, and close transitions;
- structural sole-path, no `ast.*` switch, no name gate, no fabricated value,
  zero new side-door findings, and zero panic catches.

Battleaxe validation records before/after receipts with identical discovery
scope. `Delta R` is reported only from comparable numeric fields with a proven
non-empty denominator; otherwise it is reported as unmeasured. Timeout budget
must not increase.

## Scope Boundary

This lane introduces only generator construction and the mechanical
generator-manager consumer. Generator expressions, async generators, unrelated
context-manager authorities, and warning-specific semantics are excluded unless
they pass through the same construction without additional recognition.
