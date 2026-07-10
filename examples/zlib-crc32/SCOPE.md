# zlib.crc32 logo — discrimination scope

**Surface:** CPython `zlib.crc32`.

**Mechanism:** dual-assert on shared `#euf#` key.

| Half | Assert | Role |
|------|--------|------|
| true | crc32(b"provekit") == 2526568736 | truth |
| lie | crc32(b"provekit") == 0 | lie |

Claim: **checksum equality discrimination** for the crc32 coordinate.
