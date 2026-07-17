# Divide Floor Evidence Design

## Scope

Current `origin/main` still terminates on the retained representative
`pandas/tests/scalar/timedelta/test_arithmetic.py` at `NaT / td`. The terminal
testimony is `owner=divide`, `observed=NativeCallableValue`, at line 561. This
is one live fatal-corpus file.

The left operand is an exact coordinate exported by a native extension. The
right operand is the opaque result of constructing `Timedelta`. Python must
perform `__truediv__`/`__rtruediv__` dispatch at runtime. The lifter cannot
prove the quotient, a returned sentinel, or a raised exception.

## Considered designs

1. Emit an ordinary symbolic quotient. Rejected: that fabricates successful
   arithmetic even though native division may return, refuse, or raise.
2. Keep the factory panic. Lawful but incomplete: the runtime boundary is
   already concrete enough to authenticate without inventing its outcome.
3. Construct a named authenticated runtime effect. Chosen: preserve the full
   `/` operand pair, operation name, and source locus while leaving the runtime
   verdict unresolved.

## Construction

Add `DivideRuntimeEffect` and a `runtime_divide(left, right, site)` constructor.
The constructor builds the full `/(left, right)` term and calls the existing
`runtime_effect_witness("py.divide", operand, site)` boundary.

`NativeCallableValue.divide` uses this constructor only when the right operand
is a `CallSiteValue`. This is the exact current-main shape. Numeric division
and concrete division-by-zero keep their existing implementations. Every
other `NativeCallableValue.divide` combination continues through
`FloorValue.divide` and therefore remains a loud owner-named gap.

No new Sugar class is introduced. `DivideOpSugar` remains the proof-bearing
owner and its existing truthful/lying witness pair must reach SAT/UNSAT through
the real solver.

## Measurement and discrimination

TDD first pins:

- `NativeCallableValue / CallSiteValue` produces an incomplete
  `DivideRuntimeEffect` whose witness carries both operands and the real source
  locus;
- an unsupported sibling still raises the existing `owner=divide` panic;
- the existing `DivideOpSugar` truthful/lying pair reaches opposite solver
  verdicts.

Replay only the named pandas representative. The expected owner delta is
`divide 1 -> 0`; completion or advancement must be reported by its actual next
terminal. No full-corpus sweep is part of this front.
