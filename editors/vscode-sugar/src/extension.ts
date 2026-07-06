// SPDX-License-Identifier: MIT OR Apache-2.0
//
// extension.ts: the VS Code side of slice A (#3774).
//
// It is a plain LSP-style client (no language-server framework): on every
// open / edit of a supported document it asks sugar-linkerd to re-lift and
// re-link that file, then paints the returned per-file diagnostics as red
// squiggles. The adjudication is the PRODUCTION construction (`link()` inside
// the daemon), so the editor shows exactly what the proofchain says because it
// asks it. There is no shadow verifier here.
//
// Today's daemon discharges obligations structurally (JCS-canonical implication
// / vacuous discharge); the solver-backed semantic adjudication that turns a
// literal test assertion UNSAT is slice B/C (see README).

import * as os from "os";
import * as path from "path";
import * as crypto from "crypto";
import * as vscode from "vscode";
import { LinkerdClient, kitIdForFile, LinkerDiagnostic } from "./linkerdClient";

let client: LinkerdClient | undefined;
let diagnostics: vscode.DiagnosticCollection;
const timers = new Map<string, NodeJS.Timeout>();

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  diagnostics = vscode.languages.createDiagnosticCollection("sugar");
  context.subscriptions.push(diagnostics);

  const cfg = vscode.workspace.getConfiguration("sugar");
  const socketPath = resolveSocketPath(cfg.get<string>("linkerd.socketPath") || "");
  const binaryPath = cfg.get<string>("linkerd.binaryPath") || undefined;
  const snapshotPath = socketPath + ".snapshot";

  client = new LinkerdClient(socketPath);
  try {
    await client.ensureDaemon(binaryPath, snapshotPath);
  } catch (e) {
    vscode.window.showWarningMessage(
      `Sugar: could not reach sugar-linkerd — ${(e as Error).message}`
    );
    return;
  }

  const debounceMs = cfg.get<number>("debounceMs") ?? 250;

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => scheduleLink(doc, 0)),
    vscode.workspace.onDidChangeTextDocument((e) => scheduleLink(e.document, debounceMs)),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
  );

  // Prime any already-open documents.
  for (const doc of vscode.workspace.textDocuments) {
    scheduleLink(doc, 0);
  }
}

export function deactivate(): void {
  for (const t of timers.values()) {
    clearTimeout(t);
  }
  timers.clear();
  void client?.shutdown();
}

function scheduleLink(doc: vscode.TextDocument, delayMs: number): void {
  if (doc.uri.scheme !== "file") {
    return;
  }
  const kitId = kitIdForFile(doc.fileName);
  if (!kitId) {
    return;
  }
  const key = doc.uri.toString();
  const existing = timers.get(key);
  if (existing) {
    clearTimeout(existing);
  }
  timers.set(
    key,
    setTimeout(() => {
      timers.delete(key);
      void linkDocument(doc, kitId);
    }, delayMs)
  );
}

async function linkDocument(doc: vscode.TextDocument, kitId: string): Promise<void> {
  if (!client) {
    return;
  }
  try {
    const diags = await client.parseFile(kitId, doc.fileName, doc.getText());
    diagnostics.set(doc.uri, diags.map((d) => toVsDiagnostic(doc, d)));
  } catch (e) {
    // A lifter-unavailable / kit-not-in-manifest error is not a proof failure;
    // surface it as an information diagnostic-free notice rather than a squiggle.
    console.error(`sugar: parseFile failed for ${doc.fileName}: ${(e as Error).message}`);
  }
}

/** Turn one linkerd diagnostic into a VS Code diagnostic anchored at its locus. */
function toVsDiagnostic(
  doc: vscode.TextDocument,
  d: LinkerDiagnostic
): vscode.Diagnostic {
  const range = rangeFor(doc, d);
  const message =
    `${d.errorKind}: ${d.reason}` +
    (d.targetSymbol ? `\n  target: ${d.targetSymbol}` : "");
  const diag = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
  diag.source = "sugar-linkerd";
  diag.code = d.errorKind;
  return diag;
}

function rangeFor(doc: vscode.TextDocument, d: LinkerDiagnostic): vscode.Range {
  const locus = d.callSiteLocus;
  const line1 = locus?.line ?? undefined;
  if (typeof line1 === "number" && line1 > 0) {
    const line0 = line1 - 1;
    const col = typeof locus?.column === "number" ? locus.column : 0;
    // Prefer the word at the call site; fall back to the whole line.
    const wordRange = doc.getWordRangeAtPosition(new vscode.Position(line0, col));
    if (wordRange) {
      return wordRange;
    }
    const lineText = line0 < doc.lineCount ? doc.lineAt(line0) : undefined;
    if (lineText) {
      return lineText.range;
    }
    return new vscode.Range(line0, col, line0, col + 1);
  }
  // Locus without a line: anchor to the top of the file.
  return new vscode.Range(0, 0, 0, 1);
}

function resolveSocketPath(configured: string): string {
  if (configured) {
    return configured;
  }
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.homedir();
  const hash = crypto.createHash("sha256").update(root).digest("hex").slice(0, 16);
  return path.join(os.tmpdir(), `sugar-linkerd-${hash}.sock`);
}
