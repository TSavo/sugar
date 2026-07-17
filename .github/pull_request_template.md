<!--
Construction / wall PRs: this template is orientation, not a gate.
Predicted Epsilon R is cheap. Measured Delta R is minted post-merge by
pandas-wall.yml / numpy-wall.yml against the #4102 ledger (#4263).
-->

## Summary

<!-- What changed and why. -->

## Predicted Epsilon R (construction / wall lanes)

<!-- Required when the PR touches construction, recovery, factory, floors, or
wall tooling. Prediction is not a gate — fill it even when the predicted
delta is zero. Leave the table and write "n/a — not a construction PR"
otherwise. -->

| bucket | predicted Δ | why |
| --- | ---: | --- |
| `constructed` |  |  |
| `mandatory_panics` |  |  |
| `suppressed_descendants` |  |  |
| `typed_effects` |  |  |
| `silent` | 0 | floor: must stay 0 |

A panic decrease with an unexplained suppressed increase is **not** construction
— it is a suppression shift. Own every bucket that moves.

## Validation

<!-- Focused tests / instruments run locally. Broad suites are background telemetry. -->

## Floors preserved

<!-- data_loss=0, no secret commit, no test deleted for green, silent=0. -->
