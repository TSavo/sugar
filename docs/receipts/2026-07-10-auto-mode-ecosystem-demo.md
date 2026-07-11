# Handoff O — Auto-mode ecosystem demo (itsdangerous)

**Date:** 2026-07-10  
**HEAD base:** origin/main at branch open  
**Issue:** #4007 auto-mode · Minority Report thesis #4016  

## Story

```text
pip install itsdangerous
# consumer imports it
# LSP auto-mode: cold pool entry → mint from site-packages → seal by source CID
# Minority Report of the dep: what isn't under contract you control
```

A dependency you **did not write**, under **no contract you control**, after only `pip install`.

## Auto-mode seal (real pip path)

Integration: `cargo test -p sugar-lsp --test auto_mode_ecosystem_demo`

```
auto-lift pass1:
auto-lift: itsdangerous cold → sealed via Minted
auto-lift: merged 1 vendor proof(s) into base pool

auto-lift pass2:
auto-lift: itsdangerous warm (pool/sealed) — skip

module_root=/opt/data/py-site/itsdangerous disk_proofs=1
```

| Pass | Result |
|------|--------|
| 1 (cold) | **Minted** vendor proof into base pool |
| 2 | **warm skip** (process sealed) |
| Disk | `.sugar/imports/auto/<source_cid>.proof` **present** (1) |

Seal order exercised: cold → mint → durable disk → warm free.

## Minority Report of pip-installed `itsdangerous`

Instrument: per-file `lift_file_payload` + `account_lift_coverage` + AST `census_paths`.

| Axis | Count |
|------|------:|
| `.py` files | 8 |
| **On-disk asserts (stated claims)** | **0** |
| **Function bodies (AST census)** | **62** |
| silently_unaccounted (Crime 1) | 0 (nothing to silence — no asserts) |
| dig_floors / forged_warrant (Crime 2) | 0 / 0 |
| **census_disagreement files** | **8/8** — every module has bodies with **0** collapse function-contract rows |

### Per-module census vs collapse (lift hole / Minority mass)

| file | census bodies | collapse rows |
|------|--------------:|--------------:|
| `__init__.py` | 1 | 0 |
| `_json.py` | 2 | 0 |
| `encoding.py` | 5 | 0 |
| `exc.py` | 6 | 0 |
| `serializer.py` | 21 | 0 |
| `signer.py` | 15 | 0 |
| `timed.py` | 10 | 0 |
| `url_safe.py` | 2 | 0 |

**Reading:** The report body (stated asserts) is empty — green on Crime 1/2 is **comfort about claims that don't exist**. The Minority Report is the **62 voiceless bodies** and the **census_disagreement** (lift never collapsed function-contract rows for them). That is the danger surface of a dep under no test-assert contracts.

Raw JSON: `docs/receipts/2026-07-10-auto-mode-ecosystem-itsdangerous.json`

## Files

- `implementations/rust/sugar-lsp/tests/auto_mode_ecosystem_demo.rs` — CI-able ratchet of cold mint + warm skip
- this receipt

## Not claimed

- Not claiming itsdangerous is fully proven or that mint produced rich EUF contracts.
- Empty mint is still honest (zero contracts when source states none) — product law of #4007.
