# hashlib.sha256 hexdigest logo — discrimination scope

**Surface:** CPython `hashlib.sha256(...).hexdigest()`.

**Mechanism:** dual-assert on a shared `#euf#` key (not closed-strip ambient).
Truth and lie about the same callsite must be **unsat** together.

| Half | Assert | Role |
|------|--------|------|
| true | hexdigest == real sha256 of `b"x"` | truth |
| lie | hexdigest == `"00"` | lie |

Claim of record: **digest equality discrimination** for the hexdigest coordinate —
not a padding strip ambient.
