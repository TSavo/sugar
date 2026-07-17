# CallSugar runtime starred-positional design

## Context

Current main has two bounded representatives whose first terminal is
`CallSugar` while binding a starred positional argument to a constructed
`FunctionCallable`:

- `numpy/lib/_format_impl.py:408` expands the symbolic function parameter
  `version` in `magic(*version)`.
- `numpy/_core/tests/test_einsum.py:1315` expands a `CallSiteValue` returned by
  `self.build_operands(...)`.

`StarredSugar` correctly preserves both source expressions as `py.star(...)`
coordinates. The failure is later: `_expand_function_positional_args` can
expand constructed tuple/list floors, but treats every other operand as the
same missing-construction panic.

## Alternatives

1. Return either constructed positional values or a typed incomplete outcome
   from the binder. This keeps the decision at the point that knows a bound
   callable needs actual positional binding. This is the selected approach.
2. Emit an effect directly from `StarredSugar`. Rejected because external and
   coordinate-only calls may lawfully preserve a symbolic star without binding
   it locally.
3. Create an unknown-expanded-arguments floor. Rejected because it would let a
   call appear constructed without knowing its arity or formal bindings.

## Design

`_expand_function_positional_args` retains its tuple result for ordinary and
constructed tuple/list operands. For a `SymbolicValue`, it returns
`Incomplete(StarredPositionalRuntimeEffect)` built exclusively through
`runtime_effect_evidence("py.call.starred_positional", operand, site)`.
`CallSugar` and `KeywordCallSugar` propagate that incomplete result before
calling `FunctionCallable.callsite`.

The classification is deliberately narrow. A symbolic function parameter is
runtime-by-nature: even perfect lift machinery cannot know its future iterable
elements. A ground scalar, mapping, or other unsupported floor remains a
`FactoryPanic`. A `CallSiteValue` also remains loud in this slice: its body and
return construction must be adjudicated rather than being relabeled runtime
dependence merely because current machinery has not expanded it.

## Evidence

- Discrimination: a symbolic star produces the named typed effect; constructed
  tuple/list stars still expand byte-for-byte in source order.
- Ground wrong twin: a scalar and mapping still raise `FactoryPanic`.
- Typed-effect witness: the truthful arm matches the named effect, locus, and
  runtime reason; the wrong-reason twin refutes.
- Total invariant: every constructor site uses the RuntimeOperand evidence
  door and `CONSTRUCTOR_SITES FAILED` remains zero.
- Bounded replay: `_format_impl.py` moves `CallSugar 1 -> 0`; any next terminal
  remains named and loud. `test_einsum.py` remains `CallSugar` unless separate
  concrete evidence can retire its `CallSiteValue`.

