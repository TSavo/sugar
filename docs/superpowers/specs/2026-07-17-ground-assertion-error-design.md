# Ground False Assertion Exceptional Exit Design

## Problem

`FalseBoolLiteralSugar.stated` correctly refuses a ground false assertion, but
the exact Python `AssertionError` exceptional exit is now constructible. The
current refusal is live at `numpy/_core/tests/test_errstate.py:66`.

## Design

Add a single ground-assertion constructor beside the existing ground
`IndexError` constructor. It accepts the assertion source site, refuses an
absolute locus, hashes the cited source, constructs
`ExceptionValue("AssertionError", ())`, and returns a `RaiseValue` carrying the
matching `RaiseEffect`.

`FalseBoolLiteralSugar.stated` delegates to that constructor. `RaiseValue` is
the existing reduced control-flow outcome, so ordinary block and try handling
halts unreachable continuation or selects a matching handler. This is not a
`RuntimeEffect`: the false condition and exception class are fully decidable.

## Floors

- Ground true assertions remain empty support.
- Symbolic assertions remain propositions.
- Ground false assertions construct only `AssertionError`.
- Absolute or uncited source coordinates remain loud.
- No RuntimeEffect constructor or empty-success arm is added.

## Evidence

- Red/green discrimination for `assert 0` versus `assert 1`.
- Matching `except AssertionError` consumes the exit; a wrong handler retains
  it.
- A real-solver truthful/wrong twin proves the exceptional-exit class matters.
- Current-main replay moves the one named owner terminal with `silent=0`.
