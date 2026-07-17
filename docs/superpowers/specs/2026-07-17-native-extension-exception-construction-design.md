# Native Extension Exception Construction Design

## Scope

Current main has two bounded `RaiseSugar` terminals with
`observed=CallSiteValue`. They are semantically different:

- `pandas._libs.tslibs.IncompatibleFrequency(...)` is a statically named
  exception class exported by a pinned native extension.
- `type(err)(...)` selects an exception class from a caught runtime value.

This change constructs only the first case. The second remains the same loud
`RaiseSugar` panic because its class identity is runtime-dependent. It is not
converted to a runtime effect merely to reduce the fatal count.

## Construction

The install-source value oracle already owns installed native-extension
symbols, but currently returns `NativeCallableValue` for every export without
examining the named export. Refine that existing owner:

1. Follow the existing single static re-export route to the extension module.
2. Load the exact named export from that pinned installed module.
3. If the export is a class and `issubclass(export, BaseException)`, construct
   `ExceptionClassValue` with the resolved qualified name.
4. Otherwise preserve the existing `NativeCallableValue` result.

No AST spelling is trusted as exception evidence. The loaded class identity
and its actual Python ancestry are the evidence.

## Failure Semantics

Import failure, a missing export, ambiguous re-export, or a non-exception
export does not gain exception authority. Existing construction behavior
continues, and `RaiseSugar` remains loud if the resulting value is not an
`ExceptionValue`.

No runtime-effect constructor is added or touched. In particular,
`type(err)(...)` remains loud: although it is runtime-dependent by nature,
this slice does not add a typed effect representation for dynamic exception
class selection.

## Tests and Receipt

- RED/GREEN discrimination: `_csv.Error` constructs
  `ExceptionClassValue`; `_csv.Dialect` does not.
- Raise discrimination: `raise Error(...)` constructs an exact
  `ExceptionValue`; `raise Dialect(...)` remains a named `RaiseSugar` panic.
- The `RaiseSugar` verdict witness uses the native exception path; truthful is
  satisfiable and the lying twin is unsatisfiable.
- Named replay conservation:
  `pandas/core/resample.py` moves from one `RaiseSugar` terminal to zero;
  `pandas/core/groupby/groupby.py` remains one loud `RaiseSugar` terminal;
  silent movement is zero.

