# Import Alias Value Construction Design

## Problem

The fatal recensus at `320b87cc` found six files whose first terminal owner is
`ImportAliasValue` and two whose owner is `ImportAliasValue.truth`. The six
primary files use two-argument `getattr` against an imported module or class
whose qualified identity is fixed at lift time. The truth files import
source-backed boolean/predicate flags whose defining value was not carried into
the import binding.

The existing floor correctly refuses to turn these ground import coordinates
into generic runtime effects. The missing construction is the exact imported
coordinate or source-backed value.

## Construction

`GetattrBuiltinSugar` first retains the existing install-source value resolver.
When that resolver cannot construct a value, `ImportAliasValue` may authenticate
the requested static attribute:

1. Resolve the alias's exact import target.
2. Import only that target and authenticate its concrete object identity.
3. Return an `ImportAliasValue` for the exact qualified requested attribute;
   the coordinate records the lookup without claiming that lookup succeeds.
4. When import or attribute identity is unavailable, return no construction and
   follow the existing loud `ImportAliasValue` floor.

For source-backed from-import flags, the existing
`resolve_install_source_value` door remains the only constructor. The module
seed attaches the resolved value to `ImportAliasValue`, and `truth()` delegates
to that value. Any unresolved flag retains the current
`ImportAliasValue.truth` panic.

## Boundary

- Qualified imported-object attributes construct `python:import_alias`
  coordinates.
- Concrete imported classes continue to construct `python:type` only where a
  type tester asks for that coordinate.
- No ground coordinate may mint RuntimeEffect authority.
- No `None` result is interpreted as success.
- No empty payload or suppressed assertion is accepted.
- Dynamic attribute names and genuinely runtime calls use only their existing
  sealed effect doors.
- Missing modules, missing attributes, and source values with no single
  constructible identity stay loud.

## Verification

- Direct pytest discrimination covers a concrete qualified attribute and a
  missing attribute that must still panic.
- Direct pytest covers `NUMEXPR_INSTALLED` and `HAS_PYARROW` source-backed truth
  construction while retaining an unresolvable truth bad twin.
- The eight named recensus representatives are replayed without a full corpus
  sweep. Their terminal movement is conserved and `silent=0`.
- The claim-mass direct-pytest tripwire is run and any moved pin is updated
  loudly rather than bypassed.
- A fresh local binary produces a provenance-matched truthful/lying
  witness pair with distinct verdicts.
