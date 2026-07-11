# Silent-drop ratchets after #4154 warm-overlay

## Law

Any warm/overlay path that **drops** a vendor ambient post without **degrade** is a law violation (silent green class — #4148 / #3802 / #3808).

#4154 already:

1. Records `dropped_ambient_posts` at specialization (open / decode-fail / opaque)
2. `assess_dropped_ambient_posts` → degrade under declared post-bearing deps
3. Integration: open-post planted lie degrades; closed twin still flips

This PR **pins the assess + partition halves** so regressions fail red without re-deriving the full mock-kit path.

## Instruments

| Test | Package | Asserts |
|------|---------|---------|
| `silent_drop_ratchet_open_post_after_specialization_is_loud` | sugar-verifier | open post → dropped, not kept |
| `silent_drop_ratchet_closed_post_is_kept_not_dropped` | sugar-verifier | closed post → kept, empty dropped |
| `silent_drop_ratchet_call_term_missing_args_is_loud_decode_fail` | sugar-verifier | missing-args ctor → CallTermDecodeFailed |
| `silent_drop_ratchet_dropped_reason_labels_are_stable` | sugar-verifier | reason labels load-bearing |
| `assess_dropped_ambient_posts_loud_under_declared_deps_silent_drop_ratchet` | sugar-lsp | non-empty drops under deps → Err (all 3 reasons); empty → Ok; no deps → Ok |
| `open_post_degraded_reason_is_assess_channel_not_silent` | sugar-lsp | solve_buffer degraded_reason is assess channel + open-after-specialization |

## Auto-mode / download-sources edge

Once a post-bearing vendor proof lands under `.sugar/imports` (cold mint, shipped `.proof`, disk auto cache, or Download sources sdist seal — seal order #4012/#4108), the project is **declared deps**. The same `assess_dropped_ambient_posts` gate applies; there is **no** separate auto-mode path that may un-degraded-green when drops are non-empty.

Instrument: pure assess + staged imports proof only — **does not** thrash full numpy suite.

## Receipts (paste)

```text
cargo test -p sugar-verifier --lib silent_drop_ratchet -- --nocapture
# 4 passed

cargo test -p sugar-lsp --test warm_overlay_soundness -- --nocapture
# 10 passed
# RECEIPT open-post: degraded=true reason=... open-after-specialization ...
# RECEIPT consumer-bad: unsatisfied; consumer-good: discharged
```
