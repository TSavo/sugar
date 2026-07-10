# hmac.compare_digest logo — discrimination scope

**Surface:** CPython `hmac.compare_digest(a, b)`.

**Mechanism:** dual-assert on shared `#euf#` key (not strip ambient).

| Half | Assert | Role |
|------|--------|------|
| true | compare_digest(b"a", b"a") == True | truth |
| lie | compare_digest(b"a", b"a") == False | lie |

Claim: **boolean outcome discrimination** for the compare_digest coordinate.
Constant-time comparison is not modeled; equality of the bool result is.
