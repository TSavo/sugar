# Ground IndexError Exceptional Exit Design

## Scope

Two current-main pandas files terminate at `owner=ListValue.subscript` after a
concrete empty list is indexed at concrete index zero:

- `pandas/core/internals/managers.py`
- `pandas/core/reshape/merge.py`

The receiver, index, and bounds check are all lift-time facts. Python's next
step is therefore exactly known: execution raises `IndexError`. The lift must
construct that exceptional exit, not mint runtime-effect authority and not
pretend the expression returned normally.

## Construction

`ground_index_error` becomes the single constructor for the exceptional exit
already demanded by list, tuple, and string ground sequence floors. It builds:

- an exact `ExceptionValue("IndexError", ...)`;
- a source-cited `RaiseEffect("IndexError", locus, source_sha256)`;
- a `RaiseValue` carrying both.

The result is a normal completed control-flow value. It is not an
`Incomplete`, `RuntimeEffect`, or empty success.

`Complete.and_then` preserves a `RaiseValue` unchanged instead of handing it
to the next expression step. This models Python evaluation order: once a
subexpression raises, outer calls, operators, assignments, and returns do not
execute. At block level the existing `RaiseValue` follow and contribution
protocol halts the path and lets `TrySugar` route a matching `except
IndexError`.

## Refusal Boundary

Only a concrete integer index outside a concrete sequence's bounds reaches
this constructor. Symbolic or runtime-selected indices retain their existing
proof-bearing subscript coordinate or loud floor. Missing subscript machinery
is not relabeled as an exception or runtime effect.

Absolute, uncanonicalized source loci remain a loud construction panic.

## Receipt

- Discrimination: `[][0]` constructs `RaiseValue(IndexError)`; `[1][0]`
  returns the element.
- Propagation: an outer operation after `[][0]` is not evaluated.
- Routing: `try: [][0]` reaches `except IndexError`; the wrong handler does
  not.
- Verdict witness: truthful routed handler is SAT; lying twin is UNSAT.
- Named replay: both pandas representatives move from
  `ListValue.subscript` to either completion or a distinct loud owner;
  `silent=0`.
- RuntimeEffect constructor-site census remains at zero failures.

