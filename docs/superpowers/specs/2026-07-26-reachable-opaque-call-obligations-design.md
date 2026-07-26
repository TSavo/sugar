# Reachable Opaque-Call Obligations for Assertion-With

## Objective

Construct a source-authenticated `pytest.raises(...)` context manager without
adding a pytest name arm or a second evaluator.

The concrete defect is in source-call frame preparation. The authenticated
`pytest.raises` function has a context-manager route when variadic positional
`args` is empty and a legacy callable route containing `func(*args[1:],
**kwargs)`. Current frame preparation scans the entire function before binding
actuals and aborts at the unresolved free call target `func`, even though the
empty-`args` context-manager route returns before that call can execute.

The missing general law is:

> An unresolved source call is a typed obligation at its exact source
> coordinate. It refuses construction if and only if ordinary Sugar reduction
> reaches that coordinate. Unreachable obligations are deferred, never erased
> or discharged.

## Scope

This cut changes source-visible call construction only.

In scope:

- carry unresolved-call obligations by exact call coordinate;
- let ordinary source reduction decide reachability after authenticated actual
  binding;
- raise the existing typed `opaque-call-target:<name>` refusal when a deferred
  coordinate is reached;
- construct the existing `EffectBoundarySemanticsV1` through the current
  manager protocol and summary derivation once the reachable manager route
  succeeds.

Out of scope:

- pytest, pandas, or vendor-name dispatch;
- a contract admitted from callable spelling or signature shape;
- pre-pruning the AST with a second evaluator;
- changes to `ExitSet`, partition testimony, or resource-With semantics;
- census, scoreboard, baseline, or pin work.

## Architecture

### 1. Typed obligation

Add an immutable `OpaqueSourceCallObligationV1` beside
`TreeConstructionContextV1` in
`sugar_lift_py_tests.context_manager_resolution`. The lower package owns the
transport type so `sugar-source-tree` never imports the higher
`sugar-lift-python-source` package. The source-construction package only mints
the obligation. It records:

- the exact `SourceFragmentCoordinateV1` of the unresolved `Call`;
- the unresolved target name, such as `func`;
- the authenticated resolved-object CID whose source frame contains the call.

The obligation is testimony about a missing callee frame. It is not a
resolution, a placeholder return value, or evidence that the call is safe.

### 2. Construction-context transport

Extend `TreeConstructionContextV1` with an initially empty coordinate-keyed
table of opaque-call obligations. The table follows the same source-call
construction lifetime as `source_call_frames`.

During `resolve_source_visible_frame`:

- source-resolvable external callees continue to populate
  `source_call_frames`;
- unresolved callees no longer abort the containing function;
- each unresolved call coordinate receives one obligation;
- duplicate writes must agree exactly, otherwise construction raises a backend
  defect rather than selecting one.

The eager scan still discovers and records obligations, but it no longer
decides whether they are reachable.

### 3. Reachability door

At `Call.sugar`, before ordinary call construction:

- look up the call coordinate in the construction context;
- if an opaque-call obligation exists, raise the existing source-construction
  gap with kind `opaque-call-target` and detail equal to the recorded target;
- otherwise follow the existing source-frame or ordinary call path unchanged.

This makes ordinary Sugar control flow the only reachability engine. A branch
not reduced never asks its nested call for Sugar and therefore never consumes
or deletes its parked obligation.

### 4. Manager construction result

For `pytest.raises(ValueError)`:

1. authenticated dependency resolution selects the real exported function;
2. frame preparation parks the legacy `func(...)` obligation;
3. authenticated empty variadic actuals select the context-manager return
   route;
4. the parked coordinate is never reached;
5. the returned manager protocol constructs;
6. existing `derive_manager_summary` produces
   `EffectBoundarySemanticsV1`;
7. existing `WithEffectBoundarySugar` routes the matching raise over the
   factored `ExitSet`.

No special case in these steps knows the names `pytest` or `raises`.

## Error Semantics

- Reaching a parked call must raise a typed gap whose externally visible kind
  is exactly `opaque-call-target:func` for the lying twin.
- An unreachable obligation remains in the construction context after the
  truthful route completes. Tests must inspect the table so a patch that drops
  obligations cannot pass.
- A coordinate collision with conflicting target or owner testimony is a
  backend defect.
- A resolvable external frame and an opaque obligation may not coexist at the
  same coordinate.
- Existing later-stage `force-floor`, `non-manager-result`,
  `protocol-construction`, and `summary-derivation` gaps remain unchanged.

## Tests

### Real reproducer

Use a reduced pandas-style assertion boundary:

```python
import pytest

def f():
    with pytest.raises(ValueError, match="boom"):
        raise ValueError("boom")
```

It must pass through authenticated dependency resolution and source-derived
manager construction, not a hand-built contract-ref table.

### Truthful twin

The context-manager form above supplies no legacy callable arguments.

Before production changes, the test must fail on base
`e0350dc43693cd86ac14017f7e72729e907d1c36` with
`opaque-call-target:func`. After the change it must construct
`WithEffectBoundarySugar`, derive `EffectBoundarySemanticsV1`, and complete the
matching raise. The parked `func` obligation must still be present in the
construction context.

### Lying twin

Use the legacy callable route:

```python
pytest.raises(ValueError, func)
```

Binding actuals makes `func(*args[1:], **kwargs)` reachable. The test must
assert the exact typed refusal `opaque-call-target:func`; any-red is
insufficient.

### Additional law tests

- a source-resolvable external callee still installs and uses its real frame;
- conflicting obligations at one coordinate refuse loudly;
- a coordinate cannot hold both a frame and an opaque obligation;
- an unrelated ordinary call without an obligation follows the existing path.

### Verification

Run:

- the new focused truthful and lying twins;
- all tests in the owning `sugar-lift-python-source` package, printing
  per-target results and using `--no-fail-fast` for any Cargo leg;
- existing source-tree authenticated EffectBoundary tests affected by the
  construction-context schema.

The focused outcomes must retain zero crash and timeout rows. No corpus sweep
is part of this cut.

## Acceptance

The cut is complete when:

1. the truthful twin is recorded red at base `e0350dc43` for
   `opaque-call-target:func`;
2. it becomes green through source-derived EffectBoundary construction;
3. the lying twin remains red for exactly `opaque-call-target:func`;
4. the obligation is demonstrably parked rather than erased;
5. focused owning-package tests pass, with any pre-existing failures named
   separately;
6. no focused crash or timeout axis increases.
