# `--report --visual` prints actual Minority Report source

## Bug
`sugar lift --report --visual` used a separate renderer that skipped dual-axis
`liftCoverage` entirely. Even plain `--report` only printed `file:line  name`
for un_asserted bodies — not the source.

## Fix
1. Wire `render_lift_coverage_human` into `render_visual_source_report` after the plan roll call.
2. Load unaccounted loci from disk and print numbered source lines:
   - silent asserts: the assert line (RED)
   - un_asserted bodies: def + indented suite (indent walk, cap 64 lines)
3. Preview only as last-resort when file unreadable.

## Verify
```
cargo test -p sugar-cli --bin sugar visual_report_prints_actual_unaccounted
cargo test -p sugar-cli --bin sugar lift_coverage_human_names
sugar lift --report --visual <itsdangerous tests>
```

Live:
```
stated=57 accounted=57 silently_unaccounted=0
Minority Report
  present=2 dug=0 un_asserted=2
    - …/test_serializer.py:29  coerce_str
        29| def coerce_str(...)
        30|     if isinstance(ref, bytes):
        …
    - …/test_signer.py:14  get_signature
        14|     def get_signature(self, key, value):
        15|         return (key + value)[::-1]
```
