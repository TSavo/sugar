# LSP report mode P2 — dig green→red + Minority yellow (#4149)

## What
- `merge_factory_walk`: warranted → WalkOpen (green); gap/effect/unresolved → DigStop (red)
- `merge_report_lift_response`: factoryWalk + liftCoverage
- `solve_buffer` best-effort `report_lift_response_for_project` on overlay
- Host status bar: `f=… dig=open/stop y=… u=…`

## Not
- Prove UNSAT is still a separate red squiggle channel
