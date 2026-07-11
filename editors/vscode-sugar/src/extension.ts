// SPDX-License-Identifier: MIT OR Apache-2.0
//
// extension.ts: thin VS Code LanguageClient host for sugar-lsp --in-process.
//
// THE PRODUCT IS THE LSP. Report mode, prove, diagnostics live in sugar-lsp
// (#4149). This host only:
//   1) spawns sugar-lsp over stdio
//   2) paints sugar/reportMode decorations when enabled
//   3) exposes Sugar: Toggle Report Mode

import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";
import { ReportModePainter, ReportModePayload } from "./reportMode";

let client: LanguageClient | undefined;
let painter: ReportModePainter | undefined;

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

  painter = new ReportModePainter();
  const reportOn = cfg.get<boolean>("reportMode");
  painter.setEnabled(reportOn !== false);

  context.subscriptions.push(
    painter,
    vscode.commands.registerCommand("sugar.reportMode.toggle", () => {
      painter?.toggle();
    }),
    vscode.commands.registerCommand("sugar.reportMode.on", () => {
      painter?.setEnabled(true);
      void vscode.workspace
        .getConfiguration("sugar")
        .update("reportMode", true, vscode.ConfigurationTarget.Global);
    }),
    vscode.commands.registerCommand("sugar.reportMode.off", () => {
      painter?.setEnabled(false);
      void vscode.workspace
        .getConfiguration("sugar")
        .update("reportMode", false, vscode.ConfigurationTarget.Global);
    })
  );

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
    middleware: {},
  };

  client = new LanguageClient(
    "sugar-lsp",
    "Sugar (report mode)",
    serverOptions,
    clientOptions
  );

  client.onNotification("sugar/reportMode", (payload: ReportModePayload) => {
    painter?.onPayload(payload);
  });

  context.subscriptions.push({ dispose: () => void client?.stop() });
  await client.start();
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
