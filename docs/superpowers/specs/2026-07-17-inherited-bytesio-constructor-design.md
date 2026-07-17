# Inherited BytesIO Constructor Design

## Scope

Construct a source class with no local `__init__` when its exact single base is
the authenticated import `io.BytesIO` (or `_io.BytesIO`) and the constructor has
exactly one positional seed argument.

## Construction

`ConstructorCallSugar` produces an `ObjectValue` with the subclass's source
methods and one structural `__bytesio_buffer__` field. The field body is the
already factory-built positional argument, so runtime call results remain
ordinary carried values rather than minting runtime authority.

## Loud boundaries

Zero or multiple arguments, keyword arguments, shadowed aliases, unresolved
bases, dynamic bases, and every non-BytesIO base remain existing loud
constructor gaps. This change adds no `RuntimeEffect`.

## Proof

A focused unit test must fail on current main, then show the exact buffer field
and subclass method after construction. A witness pair must discharge for the
truthful subclass method claim and refute its lying twin. The named NumPy
representative must advance from the inherited-constructor panic without silent
completion.
