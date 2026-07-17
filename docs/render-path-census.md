# Visual report render refusal census

This census covers the production visual-report paths in
`sugar-cli/src/cmd_lift.rs` and `sugar-verifier/src/fol_render.rs`. Test-only
assertions are excluded.

`R` for this lane is the count of **crash escapes** plus **unclassified**
production sites. Honest floors and dead arms are allowed remaining panics.
They are not R. The durable instrument
`render_panic_census_has_no_unclassified_production_escape` measures live sites
and fails while `R > 0`.

| Site | Class | Reason |
| --- | --- | --- |
| factory-walk row missing `verdict` (four consumers) | honest floor | A constructed row without a verdict violates the factory ledger. Rendering must stop loudly rather than invent a result. |
| red factory row without `reason` | honest floor | A red row without grounds has lost its provenance. The existing panic names the owner, locus, and replacement. |
| report symbol classification gap | honest floor, owned by #4388 | An unstamped or unknown symbol cannot be rendered as a proved symbol kind. This seam is excluded from this lane. |
| indexed universe identity removed from grouping map | dead | Identities and members are built by the same zip. First emission removes the nonempty entry and the emitted set prevents a second removal. |
| plain ANSI tone in the color-selection match | dead | Plain rendering returns before the ANSI-only match. |
| guarded contract-filter unwraps | dead | Each unwrap is dominated by `is_some` or an early `None` return. These are outside formula rendering. |
| ProofIR missing kind/name/body/sort/operands | rendered gap | `fol_render` is total over JSON values and emits JSON, `?`, `<missing body>`, or the logical identity for an empty connective. |
| Python payload `effects` lane | crash-door equivalent: silent loss, fixed | The kit emitted typed effects but `LiftSourceReport` dropped them. The report now carries and renders each row, including named placeholders for absent optional evidence. |
| term-ref without `termTable` / unresolved term-ref | crash escape → named gap, fixed | Render emits `<missing termTable>` or `<unresolved term-ref: …>`; symbol inventory and repeat inventory skip unresolved refs. |
| report contract CID/sort term-table resolution | crash escape → named gap, fixed | Unresolvable formula/sort slots drop from CID minting rather than panic the report path. |
| non-string `symbolKinds` testimony | crash escape → named gap, fixed | Bad membrane values become diagnostics and are dropped; remaining string kinds still hit the #4388 classification floor. |
| demand identity serialization failure | crash escape → named gap, fixed | Presentation-only demand CID falls back to `@ <unknown demand identity>`. |

The durable boundary test derives its envelope keys from
`LiftReportPayloadDto.to_rpc` and exercises empty lanes, absent optional
fields, empty connectives, and Unicode spellings. A newly introduced
production panic must be added to this table and classified deliberately.
A new crash escape must land as a named rendered gap or loud typed error,
never as silent green.
