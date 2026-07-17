# WithSugar exit suppression contracts

## Goal

Construct source-backed context-manager exit contracts for the statically
provable subset while keeping every unproved suppression decision loud.

## Proven subset

- A concrete `__exit__` body whose result folds to literal `True` suppresses.
- A concrete `__exit__` body whose result folds to literal `False`, `None`, or
  implicit `None` does not suppress.
- `contextlib.suppress(T...)` suppresses only an exception whose constructed
  type is one of the source-stated `T...` arguments.
- A `@contextlib.contextmanager` generator with `try: yield; finally: ...` does
  not suppress a body exception.
- A `@contextlib.contextmanager` generator with one statically named
  `except T:` arm that completes normally suppresses the named exception.

Anything with a symbolic return, conditional handler, re-raise, multiple
yield, unknown exception type, or unresolved source remains the existing loud
named `WithSugar` construction gap.

## Construction

Installed-source resolution must preserve the exact qualified callable and its
`contextmanager` decorator. It constructs an immutable exit contract carrying
the proven suppression disposition and any named exception types. `WithSugar`
is the sole consumer: it removes a raise contribution only when the contract
proves suppression for that exception; otherwise it preserves the raise or
panics for an unproved decision.

## Verification

Focused tests cover a suppressing manager, a non-suppressing manager, an
unproved manager that stays loud, and the NumPy `util.switchdir` representative.
No composed mint or corpus sweep is part of this branch.
