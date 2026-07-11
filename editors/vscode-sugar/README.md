# vscode-sugar — thin host for **sugar-lsp**

**The product is `sugar-lsp`.** This package is only a VS Code `LanguageClient`
shell: spawn `sugar-lsp --in-process`, forward stdio, show what the server
publishes.

| Lives in | Does not live here |
|----------|-------------------|
| Report mode (blue fact / green dig / red dig-stop / yellow Minority) | `#4149` → **sugar-lsp** |
| Prove UNSAT diagnostics | **sugar-lsp** `prove_engine` |
| Hover / code actions | **sugar-lsp** |
| Cold `sugar prove` shell-out, `proveClient.ts`, linkerd daemon | **deleted** |

## Report mode UI

- Setting: `sugar.reportMode` (default **on**)
- Commands: **Sugar: Toggle Report Mode** / On / Off
- Status bar: `Sugar report` — click to toggle
- Server sends `sugar/reportMode` after each in-process solve; host paints decorations only when enabled.

## Configure

- `sugar.lsp.binaryPath` — absolute path to `sugar-lsp` (`bin/sugarbin --bin sugar-lsp`)
- `sugar.prove.pythonBinDir` / `sugar.prove.pythonPath` / `sugar.prove.rustBinDir` — env for the **LSP child** only

## Tests

- `npm run lsp-e2e` — protocol-level flip against real `sugar-lsp --in-process` (not Electron)

## History

Earlier prototypes: bespoke linkerd socket client, then client-side `proveClient`
shelling `sugar prove`. Those are gone. Report mode and the wall are server
work; the extension must not re-implement them.
