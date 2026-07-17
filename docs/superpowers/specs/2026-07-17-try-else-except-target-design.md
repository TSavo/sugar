# Try/else exception-target binding design

## Live frontier

Current main leaves two named NumPy representatives at
`owner=TemporalContext`, but reduction shows they are two mechanisms:

- `_format_impl.py` uses `e2` inside `except SyntaxError as e2` in a try that
  also has an `else`.
- `test_overrides.py` assigns `exc = e` only on an exception path, then reads
  `exc` after a try whose normal path also continues.

`TrySugar._desugar_else` reduces each handler body without installing the
handler's `as` target. The terminal-handler and no-else paths already construct
the correct `ScopeRebind` to a source-cited `py.except` `CallSiteValue`.

## Construction

Give all handler-reduction paths one helper that:

1. selects the handler's temporal input scope from the actual reduced raise
   path;
2. constructs the source-cited caught-exception `CallSiteValue`; and
3. installs `ScopeRebind(as_name, caught_exception)` only when the handler
   declares a target.

The `else` path then uses the same helper as the other two paths. This is a
static binding construction: no RuntimeEffect is introduced.

The post-try `exc` representative is not retired by this construction. Its
normal continuing path has no `exc`, and the selected callable comes from
runtime `getattr(np, name)`. Making `exc` definite would suppress a real
possibly-unbound path. It remains a loud `TemporalContext` residual for
separate adjudication.

## Loud boundary

An unnamed handler does not bind an exception target. Referencing such a name
continues to panic at `owner=TemporalContext`. Dynamic handler selection keeps
its existing RuntimeOperand-backed effect behavior; this change does not
broaden it.

## Receipt

- bounded replay moves the join-eligible representative from
  `owner=TemporalContext` to completion and preserves the conditional
  continuation representative as loud;
- a focused named-handler/unnamed-handler discrimination pair stays
  constructed-versus-panic;
- a `TrySugar` truthful/lying witness is SAT/UNSAT;
- conservation reports every terminal movement and `silent=0`.
