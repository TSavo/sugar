# itsdangerous logo — discrimination scope

Ambient post on `call:itsdangerous.encoding.base64_encode` is the **closed strip** universe:

```text
¬suffix-of("=", out)
```

(from grounding path #3939 / #3949 / #3956 walk-only open dig).

## What the logo dual-assert proves

| Twin | RHS | Prove |
|------|-----|--------|
| `good/` | unpadded `b"cHJvdmVraXQ"` | **discharged** |
| `bad/` | padded `b"cHJvdmVraXQ="` | **unsatisfied** |

Same `#euf#` key; the padded claim contradicts the ambient no-suffix post.

## What it does **not** claim

| Twin | RHS | Prove (instrumented) |
|------|-----|----------------------|
| `wrong-unpadded/` | wrong last char, still unpadded `b"cHJvdmVraXR"` | **discharged** (out of scope) |

A non-suffix base64 corruption does not violate `¬suffix-of("=", out)`. Catching that would need a stronger ambient (full encode theory / open dig EUF tower in ambient), which currently encoding-STOPs beside `str.suffixof` (#3956 boundary).

**Claim of record:** the logo ratchet is **padding / trailing-`=` discrimination only**, not total base64 injectivity.
