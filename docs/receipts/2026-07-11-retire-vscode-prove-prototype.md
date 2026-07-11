# Retire vscode proveClient prototype

## Law
**The product is sugar-lsp.** Report mode (#4149) is an LSP concern.
vscode-sugar is a thin LanguageClient host only.

## Deleted
- `editors/vscode-sugar/src/proveClient.ts` (cold `sugar prove` shell-out)
- `editors/vscode-sugar/src/timing.ts`
- e2e tests that claimed the extension "runs proveClient"
- package.json `prove-e2e` / `rust-prove-e2e` scripts + cold prove settings

## Kept
- `extension.ts` thin host
- `lsp-e2e` against real sugar-lsp
- PATH/PYTHONPATH settings for the LSP child process
