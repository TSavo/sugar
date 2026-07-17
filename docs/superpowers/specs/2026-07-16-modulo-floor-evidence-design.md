# Modulo Floor Evidence Design

## Scope and verified live terminal

Current `origin/main` terminates on one verified representative:
`pandas/tests/scalar/timedelta/test_arithmetic.py:878:12`,
`owner=modulo`, `observed=TermValue`. Instrumented replay identifies the
expression as `15 % td`, where `td` is
`CallSiteValue(target_name="Timedelta", body=None)` with the source-authenticated
term `call:Timedelta(kw("minutes", 3))`.

The divisor is therefore a value that exists only when the opaque native
constructor runs. Perfect lift-time machinery cannot decide the Python
`__mod__`/`__rmod__` dispatch outcome from the available source.

## Considered designs

1. Emit an ordinary symbolic remainder. Rejected: it fabricates successful
   arithmetic even though runtime dispatch may return or raise.
2. Keep every non-literal peer on the modulo panic. Sound but incomplete: this
   specific operand has enough evidence to authenticate genuine runtime
   dependence.
3. Construct a narrowly admitted named runtime effect. Chosen: it preserves
   the full operation, operand pair, and locus without claiming an outcome.

## Construction and #4265 door

Add `ModuloRuntimeEffect` and
`runtime_modulo(left, right, site)`. The helper builds
`ctor("%", [left.to_term(...), right.to_term(...)])` and authenticates it with
`runtime_effect_witness("py.modulo", operand, site)`.

`TermValue.modulo` enters this arm only when the right operand is exactly a
`CallSiteValue` whose `body is None`. A callsite with a real diggable body is
the #4265 wrong twin: its value is not runtime-dependent by nature, so it must
remain a loud `owner=modulo` FactoryPanic until its construction is implemented.
Every other unhandled peer also remains on the default modulo floor.

Existing `TermValue % TermValue` construction and concrete modulo-by-zero
effects are unchanged. No new Sugar is introduced; `ModuloOpSugar` remains the
proof-bearing owner.

## Measurement and conservation

TDD pins:

- opaque `CallSiteValue(body=None)` divisor -> witnessed
  `ModuloRuntimeEffect`;
- real diggable-body callsite divisor -> `FactoryPanic owner=modulo`;
- concrete literals -> exact `Complete(TermValue(...))`;
- unsupported string formatting shape -> existing loud panic;
- the registered `ModuloOpSugar` truthful/lying pair -> SAT/UNSAT.

Replay only the one named pandas representative. Required accounting:
`owner=modulo 1 -> 0`, with the actual next terminal or completion named.
The mass moves from one mandatory panic to one authenticated typed runtime
effect; `suppressed_descendants=0` and `silent=0`. No full-corpus sweep is in
scope.
