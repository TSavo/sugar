# hashlib.sha256 digest length logo — discrimination scope

**Surface:** CPython `len(hashlib.sha256(...).digest())`.

**Bug-shape class:** **length/bounds invariant** (not padding strip).

| Half | Assert | Role |
|------|--------|------|
| true | len(digest()) == 32 | truth |
| lie | len(digest()) == 16 | lie |

Claim: SHA-256 digest length is 32 bytes on the callsite coordinate.
