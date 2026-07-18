# Constructor Initializer Call Factory Design

## Goal

Make the factory grammar boundary the sole recognizer for initializer-body call
shapes. `constructor_call_sugar.py` must contain no inline `ast.*` shape
classification.

## Architecture

`SourceFragment` will expose one typed initializer-call recognizer. It
classifies an expression statement as exactly one of:

- `super().__init__(...)`;
- authenticated `DeclaredBase.__init__(self, ...)`; or
- zero-argument `self.method()`.

The recognizer returns source fragments for the call arguments and the
recognized coordinate. Constructor construction consumes that testimony; it
does not reopen or inspect the AST.

The remaining initializer statement-door and class-binding questions will also
use typed `SourceFragment` accessors. This removes every `ast.*` reference from
`constructor_call_sugar.py`, not only the two initializer helpers.

## Failure Semantics

Recognition is exact. Unknown calls, unauthenticated bases, unresolved
`super()`, argument-bearing self methods, and undiggable bodies remain loud
`FactoryPanic` paths. No RuntimeEffect or empty-success path is added.

## Instrument

A static test scans `constructor_call_sugar.py` and stays red while any
`ast.*` reference or retired helper name remains. Its replacement message names
`SourceFragment.initializer_call_site`.

## Discrimination

The existing super, asserted, and explicit-base witness pairs remain. Focused
tests must also prove:

- authenticated explicit base constructs;
- non-base explicit init stays loud;
- resolvable super constructs;
- unresolved super stays loud; and
- invalid native `BytesIO` initializer shapes stay loud.

