# Nested-Tuple For/Else Construction Design

## Scope

Drain issue #5287's two current-main `python.factory / For -> statement`
terminals. Both SQLAlchemy loci use the same target shape:
`Tuple[Name, Tuple[Name, Name]]` with a non-empty `else` block.

The historical #5143 work constructed simple-name/static loop shapes. This
design does not reopen that scope, take `Yield -> term`, or overlap any
ConstructorCallSugar or FunctionCallable claim.

## Recognition

`ForElseSugar` remains the single owner of synchronous `for/else` behavior.
Extend its factory recognizer to accept the existing centralized
`BindingShapeRecognition.for_nested_tuple_target_paths` testimony in addition
to simple-name and flat-tuple targets.

The Sugar stores normalized `(projection_path, binding_name)` leaves. No AST
shape test belongs in `ForElseSugar`; it consumes only `SourceFragment`
recognition results.

## Construction

`new()` continues to build the iterable, loop body, and else body through
`ctx.build_body`. During reduction, construct one `py.iter_elem` coordinate and
bind every normalized leaf by applying its indexed `py.subscript` projection
path. The existing carried-state, break/no-break, and else-face machinery then
reduces unchanged.

Unsupported targets remain unowned so the factory emits `FactoryPanic`. This
lane adds no RuntimeEffect, empty-success arm, vendor special case, or fallback.

## Discrimination and Witness

- A nested-tuple target with `else` selects only `ForElseSugar`.
- Existing simple-name and flat-tuple `for/else` remain owned.
- Starred/attribute/subscript target leaves remain unowned and loud.
- A verdict-bearing nested `for/else` truthful witness is SAT; its lying twin is
  UNSAT.

## Conservation

- `python.factory / For -> statement`: `2 -> 0`
- constructed `ForElseSugar`: `+2`
- typed effects: `0`
- suppressed descendants: `0`
- silent: `0`

CPython must be exactly `3.12.3`; all eight construction-floor axes retain
their teeth and remain green.
