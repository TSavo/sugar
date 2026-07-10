# stdlib base32 nopad logo — discrimination scope

**Surface:** CPython `base64.b32encode` + `bytes.rstrip(b"=")` via local
`encode_b32_nopad` — no third-party package.

**Ambient:** closed strip `¬suffix-of("=", out)` (same membrane as itsdangerous
#3960/#3977 and stdlib base64 #3993).

| Twin | RHS | Prove |
|------|-----|--------|
| good | unpadded `b"OBZG65TFNNUXI"` | discharged |
| bad | padded `b"OBZG65TFNNUXI==="` | unsatisfied |
| wrong-unpadded | wrong last char, unpadded | discharged (out of scope) |

Claim of record: **padding / trailing-`=` only**, not full base32 injectivity.
