# Constructor super-setattr residual design

## Frontier

The #5121 sealed receipts report nine `ConstructorCallSugar` terminals. A
current replay against the queued #5189 factory-routing head confirms all nine
remain live. One is the already-owned `IndexType` locus from #5094. No #5126
locus remains in this nine-file vector.

The next decidable residual is pandas `CheckedCall.__init__`:

```python
def __init__(self, f):
    super().__setattr__("f", f)
```

The attribute name is a ground string and the value is a constructor argument
already bound in the initializer scope. Perfect lift-time machinery can decide
the resulting `self.f` binding, so this is missing construction evidence, not a
runtime effect.

## Architecture

Extend the single factory grammar boundary introduced by #5189:
`SourceFragment.initializer_call_site`. It will return typed testimony for the
exact zero-argument `super()` receiver calling `__setattr__` with exactly two
positional arguments, no keywords, and a ground string attribute name.

The constructor-scoped `ConstructorInitializerCallSugar` claim consumes that
testimony and constructs a dedicated apply object. The apply object reduces the
value argument in the real constructor temporal context and returns one
`ScopeRebinds` entry for `self.<ground-name>`. No code in
`constructor_call_sugar.py` inspects AST classes or re-matches call syntax.

## Loud boundaries

- Non-ground attribute names remain `FactoryPanic`.
- Wrong arity, keywords, explicit `super` arguments, and unresolved receivers
  remain `FactoryPanic`.
- No `RuntimeEffect` constructor and no empty-success path are added.
- Runtime-dependent initializers (`PeriodArray`, `PyArrowImpl`, `SQLDatabase`,
  and `ArrowExtensionArray`) remain loud at their next honest owner.
- Inherited native constructor residuals remain loud for a separate
  construction front.

## Evidence

Test first with a discrimination pair:

- exact `super().__setattr__("f", f)` constructs `ObjectValue.f`;
- `super().__setattr__(name, f)` with a non-ground attribute name remains loud.

Add a truthful/lying solver witness for the exact binding. Replay the named
`pandas/io/clipboard/__init__.py` representative and report
`ConstructorCallSugar` terminal `1 -> 0`, including its next loud owner or
completion. Re-run the no-inline-AST audit, focused constructor tests, fresh
provenance-matched witness, and direct claim-mass tripwire if a pinned fixture
moves.

