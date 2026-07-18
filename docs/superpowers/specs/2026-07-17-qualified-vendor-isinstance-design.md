# Qualified Vendor Isinstance Coordinate Design

## Problem

For `isinstance(value, datetime.datetime)`, the imported module is known but
`AttributeSugar` currently reduces `datetime.datetime` to an ordinary
`CallSiteValue`. `CallSiteValue.test_python_type` then treats the type operand
as a runtime call result because it has no authenticated
`python_type_coordinate`. This misclassifies missing lift-time evidence as
runtime dependence and prevents the datetime full-file report.

## Construction

`AttributeSugar` will give an `ImportAliasValue` module binding one opportunity
to authenticate the requested attribute as a concrete Python class:

1. Resolve the import binding's stated module coordinate.
2. Import that exact module in the lift environment.
3. Read the named attribute and accept it only when `inspect.isclass` proves it
   is a class object.
4. Return an `ImportAliasValue` for the exact qualified class name.

`ImportAliasValue.test_python_type` already constructs
`python:type("<qualified-name>")` and dispatches the value through
`adt.is_python_type`. Reusing it keeps direct imports and qualified imports on
one coordinate path.

## Boundary

- Qualified concrete classes such as `datetime.datetime`, `decimal.Decimal`,
  and `collections.OrderedDict` construct type coordinates.
- A qualified function, constant, missing attribute, import failure, or
  non-class object does not claim the recognizer and follows the existing
  behavior.
- An unknown local type name remains a loud temporal/factory panic.
- No RuntimeEffect constructor or empty-success arm is added.

## Verification

- Discrimination: the three qualified class examples emit exact
  `adt.is_python_type(..., python:type(...))` formulas; an unknown local name
  remains loud.
- Witness: a qualified datetime type test has a truthful SAT twin and lying
  UNSAT twin on a provenance-matched binary.
- Re-shot: the checked-in real datetime source completes with all assertions
  accounted and `silent=0`, or advances to a distinct loud owner without
  suppression.
