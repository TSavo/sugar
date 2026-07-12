# #4149 P5 — report-mode workspace rollup and dependency Minority

Date: 2026-07-12

## Shipped

- `sugar-lsp` owns `WorkspaceReportRollup` and includes a ready-to-render `workspace` payload on `sugar/reportMode`.
- Workspace totals reuse the latest `liftCoverage` census; ranges are never recounted and no second aggregation census is run.
- Minority loci whose source file is outside the active buffer are emitted as URI-qualified workspace ranges. Resolvable files carry the actual body suite and remain `minority` (yellow), distinct from silent, prove UNSAT, and factory dig-stop.
- `vscode-sugar` only renders server-provided totals/ranges, including dependency documents when visible.

## Verification

```text
cargo test -p sugar-lsp --lib report_mode
8 passed; 0 failed

cargo check -p sugar-lsp
Finished dev profile

npm run compile  # editors/vscode-sugar
> tsc -p ./
```

Ratchets cover server aggregation without recounting, dependency yellow with source, and non-conflation with silent/UNSAT/dig-stop.

CodeLens remains a separate follow-up; this receipt closes only the remaining P5 workspace rollup / auto dependency-yellow portion.
