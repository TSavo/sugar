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

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as crypto from "crypto";
import * as vscode from "vscode";
import { LinkerdClient, kitIdForFile, LinkerDiagnostic } from "./linkerdClient";
import { proveProject, ProveDiagnostic, formatDetail } from "./proveClient";

let client: LinkerdClient | undefined;
let diagnostics: vscode.DiagnosticCollection;
let proveDiagnostics: vscode.DiagnosticCollection;
let proveBinaryPath = "";
let proveOnSave = true;
const timers = new Map<string, NodeJS.Timeout>();

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  diagnostics = vscode.languages.createDiagnosticCollection("sugar");
  context.subscriptions.push(diagnostics);
  proveDiagnostics = vscode.languages.createDiagnosticCollection("sugar-prove");
  context.subscriptions.push(proveDiagnostics);

  const cfg = vscode.workspace.getConfiguration("sugar");
  proveBinaryPath = cfg.get<string>("prove.binaryPath") || "";
  proveOnSave = cfg.get<boolean>("prove.onSave") ?? true;
  const socketPath = resolveSocketPath(cfg.get<string>("linkerd.socketPath") || "");
  const binaryPath = cfg.get<string>("linkerd.binaryPath") || undefined;
  const snapshotPath = socketPath + ".snapshot";

  // The link() path (bridge obligations) needs the linkerd daemon. The PROVE
  // path (native assertion vs a vendor .proof) does NOT — it shells `sugar
  // prove` and is fully independent. A linkerd failure must therefore NOT kill
  // the prove path: it is the actual red/green flip. Register linkerd's
  // listeners only if the daemon comes up; register prove unconditionally.
  const debounceMs = cfg.get<number>("debounceMs") ?? 250;
  client = new LinkerdClient(socketPath);
  let linkerdUp = false;
  try {
    await client.ensureDaemon(binaryPath, snapshotPath);
    linkerdUp = true;
  } catch (e) {
    client = undefined;
    console.error(`sugar: linkerd unavailable (link() path off): ${(e as Error).message}`);
  }

  if (linkerdUp) {
    context.subscriptions.push(
      vscode.workspace.onDidOpenTextDocument((doc) => scheduleLink(doc, 0)),
      vscode.workspace.onDidChangeTextDocument((e) => scheduleLink(e.document, debounceMs)),
      vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
    );
  }

  // The PROVE path (native assertion vs vendor .proof). A directory prove mints
  // + solves, so it runs on OPEN and on SAVE (or on keystroke debounce only if
  // the user opts out of on-save), never per-keystroke. This is the operation
  // that flips a NATIVE `assert` red/green against a loaded vendor universe --
  // distinct from link() above.
  if (proveBinaryPath) {
    context.subscriptions.push(
      vscode.workspace.onDidSaveTextDocument((doc) => void runProve(doc)),
      vscode.workspace.onDidOpenTextDocument((doc) => void runProve(doc)),
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (!proveOnSave) {
          void runProve(e.document);
        }
      })
    );
  }

  // Prime any already-open documents.
  for (const doc of vscode.workspace.textDocuments) {
    if (linkerdUp) {
      scheduleLink(doc, 0);
    }
    if (proveBinaryPath) {
      void runProve(doc);
    }
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

/**
 * Run `sugar prove --json` on the consumer PROJECT containing `doc` and paint
 * its `unsatisfied` rows as red squiggles at each row's source locus. Groups
 * diagnostics by the file the row points at (a project prove can implicate any
 * file in the project, not only the saved one). Cheap and side-effect-free
 * except for the diagnostic collection.
 */
async function runProve(doc: vscode.TextDocument): Promise<void> {
  if (!proveBinaryPath || doc.uri.scheme !== "file") {
    return;
  }
  const kitId = kitIdForFile(doc.fileName);
  if (kitId !== "python") {
    // The demo lifter (native-assertion vs vendor .proof) is python today.
    return;
  }
  const projectDir = resolveProjectDir(doc.uri);
  if (!projectDir) {
    return;
  }
  try {
    // The lifter needs a Python env with the sugar kit importable. The editor's
    // ambient env usually lacks it, so honor optional config: a bin dir prefixed
    // onto PATH and a PYTHONPATH suffix. Without these, prove mints in the
    // ambient env (works only if the kit is globally installed).
    const cfg = vscode.workspace.getConfiguration("sugar");
    const binDir = cfg.get<string>("prove.pythonBinDir") || "";
    const pyPath = cfg.get<string>("prove.pythonPath") || "";
    const env: NodeJS.ProcessEnv = {};
    if (binDir) {
      env.PATH = `${binDir}:${process.env.PATH ?? ""}`;
    }
    if (pyPath) {
      env.PYTHONPATH = process.env.PYTHONPATH ? `${pyPath}:${process.env.PYTHONPATH}` : pyPath;
    }
    const res = await proveProject({ binaryPath: proveBinaryPath, projectDir, env });
    // Rebuild the whole prove collection for this project from scratch so
    // cleared rows (green now) drop their squiggles.
    proveDiagnostics.clear();
    const byFile = new Map<string, vscode.Diagnostic[]>();
    // PROJECT-LOCAL SCOPING. A project prove can implicate any memento in the
    // pool, including a VENDOR proof's own internal assertions (e.g. the pandas
    // .proof carries 21 violations anchored at pandas' own test paths). Those
    // rows are real for the vendor but are NOT the user's code -- painting them
    // would squiggle files the user never wrote. Keep only rows whose resolved
    // file is INSIDE projectDir AND exists on disk (the consumer's own sources).
    const rootAbs = path.resolve(projectDir);
    for (const d of res.diagnostics) {
      const abs = path.resolve(
        path.isAbsolute(d.file) ? d.file : path.join(projectDir, d.file)
      );
      const inProject =
        abs === rootAbs || abs.startsWith(rootAbs + path.sep);
      if (!inProject || !fs.existsSync(abs)) {
        continue;
      }
      const list = byFile.get(abs) ?? [];
      list.push(proveToVsDiagnostic(d));
      byFile.set(abs, list);
    }
    for (const [file, list] of byFile) {
      proveDiagnostics.set(vscode.Uri.file(file), list);
    }
  } catch (e) {
    console.error(`sugar: prove failed for ${projectDir}: ${(e as Error).message}`);
  }
}

/** The nearest workspace folder for a document (its consumer project root). */
function resolveProjectDir(uri: vscode.Uri): string | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder) {
    return folder.uri.fsPath;
  }
  return path.dirname(uri.fsPath);
}

/** Turn one prove diagnostic into a VS Code diagnostic anchored at its locus. */
function proveToVsDiagnostic(d: ProveDiagnostic): vscode.Diagnostic {
  const line0 = Math.max(0, d.line - 1);
  const col = typeof d.column === "number" ? d.column : 0;
  // Anchor at the locus; span the rest of the line so the squiggle is visible.
  const range = new vscode.Range(line0, col, line0, Number.MAX_SAFE_INTEGER);
  const diag = new vscode.Diagnostic(
    range,
    formatDetail(d),
    vscode.DiagnosticSeverity.Error
  );
  diag.source = "sugar-prove";
  diag.code = d.status;
  return diag;
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
