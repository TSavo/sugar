# Report mode P0 — FACT paints blue (#4149)

## Palette (locked)
- **Blue** = facts (FACT ⊢)
- **Green** = dig open
- **Red** = dig-stop effect / crime
- **Yellow** = Minority un_asserted source
- UNSAT = red squiggle (prove channel; not walk red)

## Change
`VisualTone::{Blue,Yellow}` + ANSI; FACT annotations use Blue; Minority body source uses Yellow.

## Tests
`report_mode_fact_lines_paint_blue`, visual_report_* still green.
