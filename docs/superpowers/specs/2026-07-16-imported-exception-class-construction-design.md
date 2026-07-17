# Imported Exception Class Construction Design

## Scope

Retire the decidable `RaiseSugar / CallSiteValue / constructed exception floor`
front for imported Python exception classes. The representative is
`pandas.errors.AbstractMethodError`, whose exact installed source declares
`class AbstractMethodError(NotImplementedError)`.

## Construction

Installed-source resolution may construct an immutable `ExceptionClassValue`
only when one exact top-level `ClassDef` has a statically named base whose
ancestry reaches a seeded builtin exception class. Same-module exception bases
may be followed transitively. Imported bases may be followed only through one
exact import target. Dynamic bases, ambiguous declarations, unresolved imports,
and inheritance cycles produce no exception-class evidence.

`CallSugar` consumes this floor exactly as it consumes
`BuiltinExceptionClassValue`: it constructs the existing `ExceptionValue` with
the cited qualified exception identity and already-reduced arguments.
`RaiseSugar` remains the sole consumer that converts that instance into a
routeable raise exit.

## Soundness Boundary

Absence of `ExceptionClassValue` never implies that a class is an exception.
Ordinary imported classes, shadowed names, dynamic inheritance, and opaque
native classes remain `CallSiteValue` and therefore retain the existing named
`RaiseSugar` panic. No panic or refusal is weakened.

## Discrimination

- An exact imported subclass of a builtin exception constructs an
  `ExceptionValue` and a routeable `RaiseValue`.
- An otherwise identical imported ordinary class remains opaque and raising it
  reaches the named `RaiseSugar` gap.
- The real pandas `AbstractMethodError` representative advances from its fatal
  RaiseSugar frontier to completion or the next independently named frontier.
