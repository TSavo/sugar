# hashlib.md5 digest_size logo — discrimination scope

**Surface:** CPython `hashlib.md5().digest_size`.

**Bug-shape class:** **length/bounds invariant** (algorithm constant).

| Half | Assert | Role |
|------|--------|------|
| true | digest_size == 16 | truth |
| lie | digest_size == 32 | lie |

Claim: MD5 digest_size is 16 on the attribute coordinate.
