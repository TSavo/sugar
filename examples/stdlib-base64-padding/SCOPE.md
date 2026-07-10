# stdlib base64 padding logo — discrimination scope

Second real-name logo (after `itsdangerous-token-padding`). Ambient post on the
JWT-style unpadded composition

```text
base64.urlsafe_b64encode(data).rstrip(b"=")
```

(named here as `unpadded_urlsafe_b64encode`) is the **closed strip** universe:

```text
¬suffix-of("=", out)
```

(from grounding path #3939 / #3949 / #3956 walk-only open dig). The real name is
CPython `base64` (stdlib); the real bug shape is the padding confusion on the
unpadded-urlsafe pattern used by tokens/JWTs (same shape as
`itsdangerous.encoding.base64_encode` internals, without a third-party vendor).

## What the logo dual-assert proves

| Twin | RHS | Prove |
|------|-----|--------|
| `good/` | unpadded `b"cHJvdmVraXQ"` | **discharged** |
| `bad/` | padded `b"cHJvdmVraXQ="` | **unsatisfied** |

Same `#euf#` key on `unpadded_urlsafe_b64encode`; the padded claim contradicts
the ambient no-suffix post.

## What it does **not** claim

| Twin | RHS | Prove (instrumented) |
|------|-----|----------------------|
| `wrong-unpadded/` | wrong last char, still unpadded `b"cHJvdmVraXR"` | **discharged** (out of scope) |

A non-suffix base64 corruption does not violate `¬suffix-of("=", out)`. Catching
that would need a stronger ambient (full encode theory / open dig EUF tower in
ambient), which currently encoding-STOPs beside `str.suffixof` (#3956 boundary).

**Claim of record:** this logo ratchet is **padding / trailing-`=` discrimination
only**, not total base64 injectivity — same claim class as the itsdangerous logo
(#3977), on a second real name (stdlib `base64`).

## Relation to other showcases

| Showcase | Real name | Discrimination |
|----------|-----------|----------------|
| `itsdangerous-token-padding` | itsdangerous | padding strip on vendor `base64_encode` |
| `python-urlsafe-seam` | stdlib base64 | alphabet `+/` vs `-_` (not padding) |
| **`stdlib-base64-padding`** | stdlib base64 | padding strip on JWT-style composition |

CI ratchet: `run-logo-receipt.sh` (wired into `Makefile` `SHOWCASE_RUNS`).
