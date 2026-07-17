# Contextmanager Yielded Value Design

## Live frontier

Current main `9542278f454319d2a128825a069461ea67b37b60` replays the
11 historical `SequentialDigBody / Try / reduced guarded returns with an
unguarded fallback` representatives as:

| terminal | files |
| --- | ---: |
| `SequentialDigBody` | **2** |
| completed | **8** |
| distinct later loud owner | **1** |
| silent | **0** |

The two live files are:

- `numpy/lib/tests/test_io.py`, through installed
  `numpy.testing._private.utils.temppath`;
- `pandas/tests/libs/test_hashtable.py`, through the local
  `activated_tracemalloc`.

Both callees are `@contextmanager` generators whose bodies reduce to a
`TrySugar` `BlockValue` containing one `Incomplete` with a
`GeneratorYieldRuntimeEffect`. The effect is honest: generator suspension and
resume are runtime events. Its verdict-bearing witness also carries the exact
`py.generator_yield(<value>)` operation, so the yielded value itself is already
constructed evidence.

## Construction

The existing source recognizer remains the sole authority for the closed
contextmanager subset: exactly one yield in the protected try body, no return,
and cleanup or handler structure whose exit disposition is statically proven.
That recognition supplies two related facts:

1. the manager's `__exit__` suppression contract;
2. permission for its dig body to project the value already cited by the
   reduced `GeneratorYieldRuntimeEffect`.

`SequentialDigBody` gains an explicit contextmanager mode. Generic function
and generator bodies retain the current behavior. In contextmanager mode only,
an outcome is projectable when its reduced contribution contains exactly one
`Incomplete(GeneratorYieldRuntimeEffect)`, the witness operation is exactly
`py.generator_yield` with one argument, and there are no competing state,
return, raise, or opaque contributions. The projected entered value is a
`SymbolicValue` carrying that already-reduced argument term.

Installed-source dig and executable local `StatementFunctionDefSugar` both set
the mode only from the same source-authenticated recognizer. Local recognition
parses the function's containing source so decorator aliases are resolved by
the existing `_is_contextmanager_definition` machinery.

## Loud boundaries

- A generic generator with the same reduced effect remains a named
  `SequentialDigBody` panic.
- Multiple yields, mixed contributions, an unrecognized decorator, conditional
  cleanup, a return, or an unproved exception disposition remain loud.
- The implementation adds no RuntimeEffect constructor and no empty-success
  arm.
- It does not relabel unbuilt machinery as runtime dependence. It consumes an
  existing genuine runtime effect only to recover the exact yielded operand
  already cited in that effect's witness.

## Evidence

- Red discrimination: authenticated contextmanager reduced yield currently
  panics at `owner=SequentialDigBody`.
- Green discrimination: the same reduced outcome projects the exact yielded
  term.
- Bad twin: the identical reduced outcome without authenticated
  contextmanager mode remains a `FactoryPanic`.
- Source bad twins with multiple yields or an exit-overriding cleanup never
  acquire the mode.
- Verdict witness: truthful contextmanager entered-value assertion is SAT and
  the wrong result is UNSAT.
- Bounded replay conserves both live terminals, naming every later loud owner
  and keeping silent at zero.
- RuntimeEffect constructor-site census stays at `FAILED 0`; no effect site is
  added.
