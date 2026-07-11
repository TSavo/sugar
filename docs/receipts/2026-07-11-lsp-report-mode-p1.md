# LSP report mode P1 (#4149)

## Product
`sugar-lsp` emits `sugar/reportMode` after in-process solve.
vscode-sugar is a thin host: toggle + decorations.

## Palette
| paint | kind |
|-------|------|
| blue | fact |
| green | walk_open |
| red | dig_stop / silent / forged |
| yellow | minority |
| red wash | unsat (also diagnostic) |

## P1 scope
- Project prove rows → fact / unsat ranges
- merge_lift_coverage ready for full dual-axis when feed lands
- Host: `sugar.reportMode` setting + Toggle command + status bar

## Not yet
- factory dig-stop green→red from factoryWalk
- live liftCoverage feed into merge
