# Raise Expression Outcome Construction Design

## Scope

Current main has four `RaiseSugar` terminals in the pinned NumPy/pandas
recensus. Their reduced exception expressions expose three semantic shapes:

- a source-diggable helper returns an exact `ExceptionValue`;
- a source-diggable helper raises before the outer `raise` can execute;
- a runtime-selected callable has no lift-time exception identity.

This change constructs the first two shapes. The runtime-selected callable
remains the same named `RaiseSugar` panic.

## Construction

`RaiseSugar` consumes the reduced semantic outcome of its exception expression.
It does not inspect the original AST:

1. An `ExceptionValue` constructs the existing source-cited outer
   `RaiseValue`.
2. A `CallSiteValue` with a source body is dug through the existing callsite
   floor door. If dig yields a more precise value, `RaiseSugar` consumes that
   value recursively.
3. If source dig ends at a bodyless qualified native exception constructor,
   the install-source oracle must prove that exact loaded export is an
   exception class before its call arguments construct an `ExceptionValue`.
4. An `ExceptionalExitValue` means evaluation of the exception expression
   already raised. The outer raise is unreachable, so its exact existing
   `RaiseEffect`, locus, and source hash become the terminal unchanged.
5. A `GuardedValue` is accepted only when both reduced faces recursively
   construct raise terminals. The existing guard selects the corresponding
   terminal; no result is invented.

An opaque callsite, failed dig, non-exception ground value, or mixed guarded
face remains a named `RaiseSugar` panic.

## Trust Boundary

Source dig and reduced outcomes are the evidence. Function names, return
annotations, AST spellings, and exception-looking identifiers do not grant
exception authority. No RuntimeEffect constructor is added or changed.

## Tests and Receipt

- A helper returning a concrete exception instance constructs the outer
  `RaiseValue`.
- A helper returning a qualified native exception call constructs only after
  the loaded export is proven to be an exception class.
- A helper whose body raises constructs the existing inner exceptional exit.
- A guarded helper whose every face is an exact exception outcome remains
  guarded and exact.
- A runtime-selected callable remains a named `RaiseSugar` panic.
- A fresh file-backed truthful/lying witness reaches SAT/UNSAT.
- The four named corpus representatives conserve into completed, distinct loud
  owner, or unchanged loud rows with silent movement exactly zero.
