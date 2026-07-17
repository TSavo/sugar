# FunctionCallable unexpected-keyword construction

## Context

Current main still fails loudly while lifting
`numpy/_core/tests/test_overrides.py:356`. The callee is a locally constructed
`FunctionCallable` with fixed parameters `(array, option)`, while the source
call supplies the concrete keyword `new_option`. `FunctionCallable.callsite`
already has enough evidence to decide that Python raises `TypeError`, but its
generic `binding_ok = False` path currently reports an unbuilt binding floor.

## Design

Keep argument binding as the owner. Before the generic failed-binding panic,
distinguish the narrow case where all of the following are constructed:

- keyword names are explicit source names, not a `**` expansion;
- the callable signature is supported;
- no `**kwargs` formal exists; and
- at least one supplied keyword names no keyword-bindable formal.

That mismatch is a static exceptional exit, not runtime dependence. Construct a
`RaiseValue` carrying an exact `TypeError`, its source locus, and source hash.
This lets enclosing control-flow machinery (including exception-expecting
context managers) consume the real path outcome.

Every other failed bind retains the existing `FactoryPanic`. In particular,
symbolic mapping expansion, unsupported parameter machinery, and opaque
callsite shapes are not reclassified as effects or successful calls.

## Evidence

- Discrimination: an explicit unexpected keyword constructs `RaiseValue`;
  the same callable with a valid keyword constructs `CallSiteValue`.
- Bad twin: a symbolic `**options` expansion without a `**kwargs` formal stays
  loud at `FunctionCallable`.
- Verdict witness: a function containing the constructed mismatch under
  `pytest.raises(TypeError)` has a SAT truthful assertion and UNSAT lying twin.
- Representative replay: the named NumPy file moves
  `FunctionCallable 1 -> 0`; its next terminal, if any, remains named and loud.

