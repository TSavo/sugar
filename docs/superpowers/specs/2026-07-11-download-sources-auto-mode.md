# Download sources for auto-mode (#4106 / #4107)

**Maven-class companion to `pip install`.**  
Part of #4007. Issues: **#4106** (epic), **#4107** (MVP sdist).

## Path

```text
pip install foo
  → dist-info (Version, Project-URL Source, direct_url)
  → Download sources: PyPI sdist @ exact version
  → cache: $SUGAR_SOURCES_CACHE/<name>/<version>/src
  → auto-mode mint prefers that tree (tests/ first)
  → seal by source_cid
  → Minority Report on claim-rich tree
```

## Controls

| Env | Default | Meaning |
|-----|---------|---------|
| `SUGAR_LSP_AUTO_LIFT` | on | auto-mode master |
| `SUGAR_LSP_DOWNLOAD_SOURCES` | on (if auto on) | fetch sdist before mint |
| `SUGAR_SOURCES_CACHE` | `~/.cache/sugar/sources` | unpack cache |
| `PYTHON` | `python3` | metadata + fetch helper |

## Helper

`implementations/rust/sugar-lsp/scripts/download_package_sources.py`

- Reads `importlib.metadata` (name, version, Project-URLs)
- Fetches PyPI JSON → sdist for **installed** version
- Unpacks; records `project_urls.json` (GH Source map for later VCS)

## Seal order (updated)

1. Warm / sealed  
2. Process cache (source_cid)  
3. Vendor-shipped `.proof`  
4. Disk auto proof cache  
5. **Download sources** (if enabled)  
6. Mint from best root  

## Evidence (itsdangerous 2.2.0)

| Tree | asserts (approx) | tests/ |
|------|-----------------:|--------|
| site-packages wheel | 0 | no |
| downloaded sdist | ~57 | **yes** |

## Follow-ups

- VCS clone from `Project-URL: Source` when sdist missing  
- LSP UI “Download sources?”  
- Recursive `Requires-Dist`  
- Prefer GH tag matching Version when sdist layout is weird  

## Verify

```text
cargo test -p sugar-lsp --test auto_mode_download_sources -- --nocapture
```

## Ratchets (2026-07-11 follow-up)

| Test | Proves |
|------|--------|
| `test_download_sources_stated_assert_count_ratchet` | sdist census **stated ≥ 50** |
| `test_diggable_vendor_assert_lifts_not_silent` | diggable itsdangerous claim **lifted_cited ≥ 1** |
| `test_download_tree_still_mostly_silent_on_raw_pytest_suite` | honesty: raw pytest suite still mostly **silent** |

Mint staging **preserves package layout** + puts `src/` on PYTHONPATH so dig can resolve vendor packages.

### VCS follow-up (#4106)
- `SUGAR_LSP_DOWNLOAD_VCS=1` forces git clone from `Project-URL: Source`
- Automatic VCS fallback when sdist missing/fails
- Still open: LSP UI prompt, recursive Requires-Dist
