# Auto-mode ecosystem demo

**Handoff O** — `pip install` a real package; LSP auto-mode seals it; compute its Minority Report.

See `docs/receipts/2026-07-10-auto-mode-ecosystem-demo.md`.

## Re-run

```bash
export PYTHON=/path/to/venv/bin/python   # venv with itsdangerous
export PYTHONPATH=implementations/python/sugar-lift-py-tests/src:...
export SUGAR_LSP_AUTO_LIFT=1
export SUGAR_LSP_AUTO_TMP=/path/with/exec

cargo test -p sugar-lsp --test auto_mode_ecosystem_demo -- --nocapture
```

Minority Report numbers: lift each site-packages module via `lift_file_payload` + `account_lift_coverage` (script in receipt session / JSON artifact).
