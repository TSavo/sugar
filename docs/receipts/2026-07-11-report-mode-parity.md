# Report mode parity + Minority source in IDE (#4149)

## Thesis
Report mode is **one instrument**: IDE paint/totals = CLI `sugar lift --report` dual-axis.
Editor is a renderer; it does not invent a second census.

## Changes
1. **Minority yellow `source`** — `merge_lift_coverage` loads body text from disk
   (indent suite walk, cap 64; same algorithm as CLI #4147) into
   `ReportModeRange.source` so vscode-sugar hover shows real source.
2. **Dual-axis one-liner** — `dual_axis_one_liner(totals)`:
   `stated=… accounted=… silently_unaccounted=… | minority un_asserted=…`
   Host status bar: `Sugar S/A/silent | min=U`; tooltip carries full dual-axis.
3. **Ratchet** — pure unit tests (no full suite):
   - `dual_axis_totals_parity_with_lift_report_fixture` — itsdangerous-shaped
     totals 57/57/0 | minority 2; silent stays 0; dig-stop/unsat not invented.
   - `minority_range_includes_body_source_from_disk` — yellow carries body text.
   - `dig_stop_is_not_unsat_in_projection` — DigStop ≠ Unsat channels.

## Hard rules held
- Dig-stop red ≠ prove UNSAT squiggle.
- Yellow ≠ bug; silent stays 0 on the parity fixture.
- Incorrect construction (conflating channels) impossible under tests.

## Verify
```
CARGO_HOME=/opt/data/cargo-home RUSTUP_HOME=/opt/data/rustup-home \
  cargo test -p sugar-lsp --lib report_mode
```
