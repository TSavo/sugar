# struct.calcsize logo — discrimination scope

**Surface:** CPython `struct.calcsize("!I")`.

**Bug-shape class:** **length/bounds invariant** (format size).

| Half | Assert | Role |
|------|--------|------|
| true | calcsize("!I") == 4 | truth |
| lie | calcsize("!I") == 8 | lie |

Claim: network-endian unsigned int format size is 4 bytes.
