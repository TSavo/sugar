# Nested Attribute AugAssign Construction Design

Part of #5265 and #5254.

## Scope

Construct the one verified complementary assignment shape left outside #5258:
`AugAssign(Div, Attribute(Attribute(Name))) -> statement`, observed at
`scipy/optimize/_basinhopping.py:241:12`.

#5258 exclusively owns `Assign` tuple-unpack leaves rooted in names, attributes,
and subscripts. This change does not modify `TupleUnpackAssignSugar`, its tests,
or its recognition partition.

## Recognition

`BindingShapeRecognition` gains an AugAssign-specific dotted-target recognizer.
It returns path components only when the target is a pure name-rooted attribute
path of depth at least two attributes. `SourceFragment` exposes that testimony.

`NestedAttributeAugAssignSugar.owns()` consumes only the recognition result and
the AugAssign node kind. It performs no raw `ast` classification and no vendor
or source-name match. Existing one-attribute AugAssign Sugars retain their
partition.

## Construction

The Sugar stores:

- the recognized dotted target path;
- one factory-built `updated_value` child from `site.aug_assign_binop()`;
- the cited source site.

Building the synthetic operator expression through `ctx.build_body(...,
SugarRole.TERM)` delegates operand construction and operator selection to the
ordinary factory. Reduction therefore uses the existing floor operator
double-dispatch. A completed updated value becomes a `ScopeRebind` at the exact
dotted coordinate, matching `NestedAttributeAssignSugar`.

The Sugar introduces no RuntimeEffect constructor. Any genuine runtime
dependence produced by an operand or operator remains the already-witnessed
typed result of that child. An unrecognized target or unsupported child stays
the factory's loud `None => panic` arm.

## Evidence

The discrimination corpus has three arms:

1. the exact SciPy node selects `NestedAttributeAugAssignSugar`;
2. a nested dotted concrete division updates the exact binding and returns the
   divided value;
3. call-rooted and subscript-rooted nested receivers remain unowned and panic.

The registered Sugar carries a truthful/lying call witness. The truthful twin
asserts the divided result; the lying twin asserts the pre-update value and
must refute.

## Receipt

- Exact representative: `owner=python.factory` terminal `1 -> 0`.
- Mass movement: one file advances beyond this owner; silent `0`.
- Focused discrimination and truthful/lying witness both run.
- Python sole-construction floors report all eight axes green.
- CPython is exactly `3.12.3`.
