# binascii.hexlify logo — discrimination scope

**Surface:** CPython `binascii.hexlify`.

**Mechanism:** dual-assert on shared `#euf#` key.

| Half | Assert | Role |
|------|--------|------|
| true | hexlify(b"x") == b"78" | truth |
| lie | hexlify(b"x") == b"00" | lie |

Claim: **hex encoding equality discrimination** for the hexlify coordinate.
