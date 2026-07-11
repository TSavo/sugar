// SPDX-License-Identifier: MIT OR Apache-2.0
//
// extension.ts: thin VS Code LanguageClient host for sugar-lsp --in-process.
//
// THE PRODUCT IS THE LSP. Report mode, prove, diagnostics, and decorations
// policy live in sugar-lsp (see #4149). This file only:
//   1) resolves sugar-lsp binary + child env
//   2) starts vscode-languageclient over stdio
//
// Do not reintroduce proveClient / cold sugar prove shell-out here.

import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const cfg = vscode.workspace.getConfiguration("sugar");
  const binaryPath = cfg.get<string>("lsp.binaryPath") || "";
  if (!binaryPath) {
    vscode.window.showWarningMessage(
      "sugar: no sugar-lsp binary configured (sugar.lsp.binaryPath). " +
        "Resolve one with `bin/sugarbin --bin sugar-lsp` and point the setting at it."
    );
    return;
  }

  // The in-process engine mints an overlay of the edited buffer through the
  // SAME `sugar mint` lift plugins the consumer project ships (or auto-
  // discovers). A python/rust lifter subprocess `sugar-lsp` spawns inherits
  // `sugar-lsp`'s own environment, so PATH/PYTHONPATH configured here reach
  // it exactly as they reached the old cold `sugar mint`/`sugar prove` shell.
  const pythonBinDir = cfg.get<string>("prove.pythonBinDir") || "";
  const pyPath = cfg.get<string>("prove.pythonPath") || "";
  const rustBinDir = cfg.get<string>("prove.rustBinDir") || "";
  const env: NodeJS.ProcessEnv = { ...process.env };
  if (pythonBinDir) {
    env.PATH = `${pythonBinDir}:${env.PATH ?? ""}`;
  }
  if (rustBinDir) {
    env.PATH = `${rustBinDir}:${env.PATH ?? ""}`;
  }
  if (pyPath) {
    env.PYTHONPATH = env.PYTHONPATH ? `${pyPath}:${env.PYTHONPATH}` : pyPath;
  }

  const serverOptions: ServerOptions = {
    command: binaryPath,
    args: ["--in-process"],
    options: { env },
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: "file", language: "python" },
      { scheme: "file", language: "rust" },
    ],
    outputChannelName: "Sugar LSP",
  };

  client = new LanguageClient(
    "sugar-lsp",
    "Sugar (inline wall)",
    serverOptions,
    clientOptions
  );
  context.subscriptions.push({ dispose: () => void client?.stop() });
  await client.start();
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
