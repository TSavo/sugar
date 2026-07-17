# Sequential Terminal Construction Design

## Live frontier

Current main (`6cabd361e`) fails loudly while lifting
`numpy/f2py/symbolic.py`:

```
owner=RuntimeEffect
blame=numpy/f2py/symbolic.py:940:4
observed=py.sequential_terminal(Return)
requested=genuine runtime-dependent operand
```

`SequentialDigBody` currently sees a guarded early return and immediately
tries to describe all later control flow as
`ConditionalExpressionRuntimeEffect`. Its evidence operand contains only the
source location and AST kind, so the RuntimeOperand door correctly rejects it.
The relevant source shape is a sequence of reduced one-arm guarded returns
ending in an unguarded fallback return. Those reduced outcomes already contain
all evidence needed to construct the returned value.

## Design

Accumulate actual `GuardedReturn` outcomes while reducing a sequential dig
body. When the body reaches an unguarded `ReturnValue`, fold the accumulated
returns in reverse source order into nested `GuardedValue` nodes with the
unguarded return as the final false arm. Nesting preserves Python's
first-matching-return behavior: later guards are evaluated only in the false
arm of earlier guards.

The construction is intentionally bounded:

- it consumes reduced `GuardedReturn` and `ReturnValue` testimony, never AST
  inspection;
- it permits only guarded-return-only contributions before the fallback;
- a body with no unguarded fallback, an intervening state contribution, an
  effect, or an opaque terminal stays loud through the existing
  `FactoryPanic`;
- an actual runtime effect produced by reducing a statement still propagates
  unchanged.

No RuntimeEffect constructor is added. The invalid
`py.sequential_terminal` effect-construction path is removed because its input
is decidable.

Alternatives rejected:

- Authenticate the ground `py.sequential_terminal` token: violates the
  RuntimeOperand law and would turn unbuilt machinery into a fake effect.
- Inspect `If` ASTs and rebuild branches: repeats construction outside the
  reduced-outcome owner and diverges from nested branch semantics.
- Return an opaque call coordinate: hides constructible guarded return facts
  and loses the verdict-bearing relationship.

## Evidence

- A focused discrimination test constructs
  `GuardedValue(guard, early, fallback)` from one guarded and one unguarded
  reduced return.
- A no-fallback bad twin remains `FactoryPanic`.
- The existing verdict-bearing `if_return` early-return witness stays truthful
  `sat` and lying `unsat`; the focused reduced-outcome discrimination is what
  pins the symbolic fold itself.
- The RuntimeEffect constructor/evidence census remains zero failures.
- Bounded replay moves the representative away from the line-940
  `RuntimeEffect` terminal to completion or a distinct loud named owner, with
  silent zero.
