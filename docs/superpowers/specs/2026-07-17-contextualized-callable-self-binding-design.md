# Contextualized Callable Self-Binding Design

## Problem

Current main fails loudly while lifting installed `numpy/f2py/symbolic.py`:

```text
owner=TemporalContext
blame=numpy/f2py/symbolic.py:939:25
observed=as_expr
requested=value
```

The module factory has already constructed `as_expr` as a `FunctionCallable`.
The missing evidence is narrower: `StatementFunctionDefSugar` deferred the
callable body in a `ContextualizedDigBody` whose lexical context was captured
before the definition extended the module scope with its own name. Later,
`Expr.__rtruediv__` forces `as_expr`; its tuple branch reduces
`map(as_expr, obj)`, and the valid self-reference cannot find the callable in
the captured temporal context.

## Construction

`FunctionCallable.callsite` is the owner that knows both the exact callable
constructed by the definition and the deferred body that call will reduce. For
a `SugarBody` containing `ContextualizedDigBody`, the callsite will carry a
copy of that contextualized body annotated with the exact `FunctionCallable`.
When the body reduces, it binds only `callable.name -> callable` after restoring
the defining lexical context and overlaying curried arguments.

This is lazy fixed-point construction. A recursive reference resolves to the
same source-constructed callable, and another callsite repeats the same
bounded construction only if downstream reduction demands it. No eager
recursive body expansion occurs.

## Rejected Alternatives

1. Overlay the caller's whole temporal context. This could make the symptom
   disappear, but imported and nested functions would read caller locals as
   callee globals. It violates lexical ownership.
2. Rebuild all module callables after the module pass. That produces stale
   generations of callable bodies and still does not form an exact recursive
   fixed point.
3. Emit a RuntimeEffect for the missing name. Perfect machinery can decide
   this binding from the source definition, so an effect would be suppression.

## Loud Boundary

Only the callable's own constructed name is added. Any other missing global
continues to raise its ordinary named `TemporalContext` `FactoryPanic`. No
RuntimeEffect constructor is added or changed.

## Verification

- Red/green discrimination: a deferred callable body can resolve its own name.
- Bad twin: a different undefined name remains a loud `TemporalContext` panic.
- Verdict witness: a recursive callable truthful source is SAT and its lying
  twin is UNSAT through the production witness pipeline.
- Bounded representative: `numpy/f2py/symbolic.py` moves from
  `TemporalContext/as_expr` to either completion or a distinct loud named
  frontier, with silent count zero.
- RuntimeEffect constructor/evidence census remains at zero failures.

The automated discrimination test is the durable shell for this construction
boundary. It can retire only if callable self-binding becomes unrepresentable
as a separate step, for example by a recursive lexical-context type whose
constructor requires the callable's own binding.
