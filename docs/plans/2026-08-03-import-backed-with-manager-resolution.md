# Import-backed `With` manager resolution

## Measured problem

On the authenticated pandas 3.0.3 / 1,421-file corpus, 18
`ContextManagerResolutionConstructionGap` rows are direct, import-bound pandas
callables used as context managers. All 18 calls contain keyword arguments:
17 contain named keywords and one `TextParser` call also contains `**kwargs`.

The rows remain `runtime-selected` because the call-contract receipt surface is
deliberately positional-only. Commit `614fa939c6ed95efb7cd665da283ddfd86ca59be`
introduced that boundary together with a tooth asserting that `pair(x=1)` is
not a `call-contract-demand`. Removing the guard would make the call-contract
signature claim more than it authenticates.

## Authority and design

The existing lexical pass already emits an `import-value-use-demand` for the
callee `Name`. That receipt authenticates the exact source occurrence, import
binding, target symbol, and consumer source CID. The existing source-derived
manager producer already owns the typed parent `Call`, the manager-use
coordinate, keyword actual binding, dependency resolution, and manager protocol
construction.

The consumer will therefore:

1. retain full-call `call-contract-demand` receipts as the first authority;
2. for a typed manager `Call` with no full-call receipt, derive the exact
   coordinate of its `Call.func` child;
3. admit only the one `import-value-use-demand` whose source CID and complete
   physical coordinate equal that child;
4. pass that final-checked receipt through the existing
   `resolve_import_binding` and source-derived manager construction path.

No callee spelling or target name participates in the join. Multiple receipts
for one coordinate are a backend defect; absence stays an unresolved manager
gap.

## Discrimination teeth

- A direct imported `Name` manager with a named keyword reaches the existing
  source-derived protocol and no longer reports `runtime-selected`.
- A shadowed or otherwise non-import callee remains unresolved.
- A `TextParser`-shaped `**kwargs` call may move to the deeper
  `incomplete-call-actuals` terminal; the consumer must not fabricate support.
- The existing positional-only call-contract tooth remains unchanged and
  green: `pair(x=1)` is still absent from `call-contract-demand` rows.
- Existing imported attribute-call managers remain on the full-call receipt
  path.

## Non-claims

This wiring does not claim that all 18 managers complete. Each row is a first
terminal and may reattribute to a deeper, honestly named construction gap. It
does not widen the corpus pin, admit external dependencies, or change the
call-contract schema.
