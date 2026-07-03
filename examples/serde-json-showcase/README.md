# serde_json Showcase

This showcase adds a real Rust library logo: `serde_json`.

The GOOD suite carries exact rows from `serde_json 1.0.150` vendor tests:

- `tests/test.rs::test_write_null`
- `tests/test.rs::test_write_u64`
- `tests/test.rs::test_write_str`
- `tests/test.rs::test_write_bool`

The showcase deliberately stays inside point-wise exact assertions. Residuals
include tolerance-free but non-flat helper loops, error-string rows that require
format-macro modeling, map ordering rows behind feature configuration, and
nonfinite-float rows.

The BAD suite is an explicit contradiction twin over the same vendor value:
`serde_json::to_string(&true).unwrap()` is asserted equal to both `"true"` and
`"false"`. Consistency must refuse it, and the cargo-test witness package must
also refuse because the test really fails.

## Re-mint Receipt

Re-minted on 2026-07-03 with the current `sugar mint` pipeline. The checked-in
sealed bundles live under each suite's `.sugar/runs/` directory. Current main has
`good/` and `bad/`; there is no live `serde-good2/` sibling in this showcase.

| Suite | Old CIDs | New CIDs |
| --- | --- | --- |
| good | `blake3-512:2f855e7aa5200d459d694c82fc276088c6b9012e4ed11fa24d496759f3c21e74245b367683d5a006eab4596e5f8be83982eee9187ad1968cc4c6b06c6d3e7420`<br>`blake3-512:ffe6a99eb3d1a0ea1807ed3ac6b68a02bd8dc2a350f742d84f28532724069f822a6da598b594fda0db0af4db7a230ca66c9110c239c057e074025f63f1a8648a` | `blake3-512:75b5aba50ad81844ac266a98a1d87b5a54897b6f6093306df5450949be2cba107e067bc9cdb5437fa10c9d4b38dcb56d48b14f4f5214a63b3296b91b2d104a34`<br>`blake3-512:be5275cbe05e1ddf32305a253d64d6f66c1a4044893f8d42ebb760407449fff7a440bb89725be1459f6b269b2f96d9345c3d4bbb4481582b4ab18c64266df54a`<br>`blake3-512:c05c9fa80696142ad09c23baebcfb58c6a36c1e0ad6ca78dc74f53a63c562dca0ae2ddf3d8860662baa2726817e7f26632479027ff6391e787617fdace483dcc`<br>`blake3-512:e2ee7fa5c1f5bc5638e2b4e1be7ee092f0ffc49327b71072699fc070aa8b17eac22348bad9f0e35977fdb4857dd7a360aaeadc5585b347a3337891e9c2ff9a09` |
| bad | `blake3-512:35d7a217e82219ef813f4a339a69fde1e0b8bf7f4b092a60117cef57be4bb99678503523e5e2a62a451b3a4d50ef6d0e3d9d5ad18efa372b8ae91dba0d576213`<br>`blake3-512:75deb4277f4a0e765e29d7ebda0073e11a0a3bf50fdc6bcb09d0104104cbe79b3a92585befde5ad0c9c9208a27b138e3b2d5b9cc38da7ee10bfec01f64bbdec0`<br>`blake3-512:c7bf19b09a972292a78168c5e985749addebb2fffd2394a34c7e58316ca82d0c5affe1799c1ef3655d13d43909e14c23a5a5ed60d13f20f62cdaca583cb39897` | `blake3-512:4927aa059cab09c91e9f7a51a860ca31d67862430cfff5bd614f260fcefc5293e483e4b6290244242ae84859b388932ab0fd16d6be5ad95405a7b85345235a60`<br>`blake3-512:799038682ea4cbe3ef40df35fd3ea3b1456d29257b8b6434c055ec79ddb98c684c56043f9011e2d736c6ef51db6d85716a0aaa3ee0002d1a71358d1c77ca2233`<br>`blake3-512:c81daf160bf900401768fd5ce3c2c563f63a9a057536dd0fac212b624ae0256db36b1df622be478bf4f1ee10ce33906cff0f759691c2a64165485ab94ddb15bd`<br>`blake3-512:e58fb099f0c1cdae46040801a640d98f9847d63c2ed263cb2e07fe53271d0e0ce47d5e4ff5852f7dc57c9db27a3263059f90ec2eabf5fc58eae743655a3aa867` |

Replay receipts for the re-minted bundles assert `loadErrors=0` and `rule2=0`.
The bad twin remains load-clean but not green: the current verifier reports the
contradictory row as `unsatisfied`.
