# stdlib encode_nopad logo — discrimination scope

**Surface:** CPython `base64.urlsafe_b64encode` + `bytes.rstrip(b"=")` in local
`encode_nopad` — no third-party package.

**Ambient:** closed strip `¬suffix-of("=", out)` (same membrane as itsdangerous
logo #3960/#3977).

| Twin | RHS | Prove |
|------|-----|--------|
| good | unpadded | discharged |
| bad | trailing `=` | unsatisfied |
| wrong-unpadded | wrong last char, unpadded | discharged (out of scope) |

Claim: **padding only**, not full base64 injectivity.
