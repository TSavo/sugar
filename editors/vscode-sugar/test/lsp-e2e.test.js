// SPDX-License-Identifier: MIT OR Apache-2.0
//
// lsp-e2e.test.js: the extension's OWN witness for the-flip (retiring the
// daemon). Drives `sugar-lsp --in-process` over REAL LSP stdio
// (Content-Length framed JSON-RPC -- the exact wire vscode-languageclient's
// LanguageClient speaks) against the REAL demo fixtures
// (examples/python-base64-federation: native Python + a staged vendor
// `.proof`, no annotations, no mock lifters), and asserts T's flip:
//
//   didOpen consumer-bad's buffer  -> a RED publishDiagnostics carrying the
//                                     three-fact message (Vendor fact / Vendor
//                                     universe / Your fact / Conjoined / UNSAT)
//                                     rendered by the SERVER's fol_format.rs.
//   didChange to consumer-good's text -> publishDiagnostics clears (empty).
//   didChange back to the bad text    -> the diagnostic reappears.
//
// This is NOT a VS Code Electron host test -- per this extension's own
// established precedent (README: "A full editor E2E is not possible
// headlessly, so the LSP-protocol-level test is the receipt"), a headless
// protocol-level test against the production binary IS the receipt. The
// extension's `activate()` does nothing but hand this exact stdio pair to
// `vscode-languageclient`'s `LanguageClient`; this test drives the SAME
// server, the SAME wire, the SAME in-process construction
// (`build_prove_context_for` -> `mint_project_scratch_proof` ->
// `verify_consistency_scoped_with_base_index` -> `fol_format::format_detail`)
// end to end, with the REAL python kit -- no mock lift plugin.
//
// Env (set by run-lsp-e2e.sh):
//   SUGAR_LSP_BIN                    resolved `sugar-lsp` binary (bin/sugarbin)
//   SUGAR_BIN                        resolved `sugar` binary (bin/sugarbin), used
//                                    only to mint the VENDOR's .proof up front
//   SUGAR_PROVE_PATH                 PATH with the lifter's python on it
//   SUGAR_PROVE_PYTHONPATH_SUFFIX    the sugar-lift-py-* src roots
//   SUGAR_EXAMPLE_DIR                examples/python-base64-federation

const assert = require("assert");
const os = require("os");
const path = require("path");
const fs = require("fs");
const cp = require("child_process");

const LSP_BIN = process.env.SUGAR_LSP_BIN;
const SUGAR_BIN = process.env.SUGAR_BIN;
const EXAMPLE_DIR = process.env.SUGAR_EXAMPLE_DIR;
assert(LSP_BIN && fs.existsSync(LSP_BIN), `SUGAR_LSP_BIN must point at a sugar-lsp binary (got ${LSP_BIN})`);
assert(SUGAR_BIN && fs.existsSync(SUGAR_BIN), `SUGAR_BIN must point at a sugar binary (got ${SUGAR_BIN})`);
assert(EXAMPLE_DIR && fs.existsSync(EXAMPLE_DIR), `SUGAR_EXAMPLE_DIR must exist (got ${EXAMPLE_DIR})`);

let failures = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`ok   - ${name}`);
  } else {
    failures++;
    console.log(`FAIL - ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

function envFor(consumerDir, vendorDir) {
  const suffix = process.env.SUGAR_PROVE_PYTHONPATH_SUFFIX || "";
  return {
    PATH: process.env.SUGAR_PROVE_PATH || process.env.PATH,
    PYTHONPATH: [consumerDir, vendorDir, suffix].filter(Boolean).join(path.delimiter),
  };
}

function mint(dir, vendorDir) {
  for (const n of fs.readdirSync(dir)) {
    if (/^blake3-512_.*\.proof$/.test(n)) {
      fs.rmSync(path.join(dir, n), { force: true });
    }
  }
  fs.rmSync(path.join(dir, ".sugar", "runs"), { recursive: true, force: true });
  const r = cp.spawnSync(SUGAR_BIN, ["mint", "--out", ".", "--quiet"], {
    cwd: dir,
    env: { ...process.env, ...envFor(dir, vendorDir) },
    encoding: "utf8",
  });
  assert.strictEqual(r.status, 0, `mint failed in ${dir}: ${r.stderr || r.stdout}`);
}

function firstProof(dir) {
  const f = fs.readdirSync(dir).find((n) => /^blake3-512_.*\.proof$/.test(n));
  return f ? path.join(dir, f) : undefined;
}

// Stage the vendor .proof into a fresh consumer dir. The consumer dir is
// deliberately NEVER pre-minted: the in-process engine mints a SOURCE-OVERLAY
// scratch proof of whatever buffer text `didOpen`/`didChange` sends, so the
// on-disk `test_consumer.py` is a template only -- what matters is the text
// the LSP client streams.
// The REPO root, derived from EXAMPLE_DIR (examples/python-base64-federation).
const REPO_ROOT = path.resolve(EXAMPLE_DIR, "..", "..");
const LIFT_RPC = path.join(
  REPO_ROOT,
  "implementations",
  "python",
  "sugar-lift-py-tests",
  "src",
  "sugar_lift_py_tests",
  "lift_rpc.py"
);

// The consumer fixture lives in a tmpdir, outside the repo tree. `sugar mint`
// (the full CLI, used above for the vendor) auto-discovers the "python" lift
// component by walking up from the RUNNING BINARY's own location (always
// inside the repo checkout) -- see `component_plan::exe_relative_component_roots`.
// `sugar-lsp --in-process`'s buffer-overlay mint
// (`sugar_cli::cmd_mint::mint_project_scratch_proof`) is narrower: it reads
// ONLY `.sugar/config.toml`'s `[[plugins]]`, with no component-plan fallback.
// So the consumer fixture needs an explicit lift plugin declaration (the same
// shape `examples/python-double/.sugar/` ships), pointing at the SAME
// `lift_rpc.py` the repo's own `.sugar/components/python/manifest.toml` uses.
function writeLiftConfig(consumerDir) {
  fs.mkdirSync(path.join(consumerDir, ".sugar", "lift", "python"), { recursive: true });
  fs.writeFileSync(
    path.join(consumerDir, ".sugar", "config.toml"),
    '[[plugins]]\nname = "python-lift"\nkind = "lift"\nsurface = "python"\n'
  );
  fs.writeFileSync(
    path.join(consumerDir, ".sugar", "lift", "python", "manifest.toml"),
    `name = "python-lift"\nversion = "0.1.0"\nprotocol_version = "sugar-component/1"\nkind = "lift"\n` +
      `command = ["python3", "${LIFT_RPC.replace(/\\/g, "\\\\")}", "--rpc"]\nworking_dir = "."\n`
  );
}

function stageConsumer(work, label) {
  const vendorDir = path.join(work, "vendor");
  if (!fs.existsSync(vendorDir)) {
    fs.mkdirSync(vendorDir, { recursive: true });
    fs.copyFileSync(path.join(EXAMPLE_DIR, "vendor", "b64vendor.py"), path.join(vendorDir, "b64vendor.py"));
    mint(vendorDir, vendorDir);
  }
  const vproof = firstProof(vendorDir);
  assert(vproof, "vendor produced no .proof");

  const consumerDir = path.join(work, `consumer-${label}`);
  fs.mkdirSync(path.join(consumerDir, ".sugar", "imports"), { recursive: true });
  fs.copyFileSync(vproof, path.join(consumerDir, ".sugar", "imports", path.basename(vproof)));
  writeLiftConfig(consumerDir);
  // A template file on disk (mtime/config discovery anchor); its CONTENT is
  // irrelevant once the LSP overlay sends live buffer text, but a file must
  // exist at the path the didOpen uri names.
  const file = path.join(consumerDir, "test_consumer.py");
  fs.copyFileSync(path.join(EXAMPLE_DIR, "consumer-good", "test_consumer.py"), file);
  return { consumerDir, vendorDir, file };
}

function textWithLiteral(literal) {
  const src = fs.readFileSync(path.join(EXAMPLE_DIR, "consumer-good", "test_consumer.py"), "utf8");
  return src.replace(/== "[^"]*"/, `== "${literal}"`);
}

function assertLine(text) {
  const lines = text.split("\n");
  return lines.findIndex((l) => l.includes("encodeBase64(") && l.includes("assert")) + 1;
}

// ---------------------------------------------------------------------------
// A minimal Content-Length-framed LSP JSON-RPC client -- the exact wire
// vscode-languageclient's LanguageClient speaks to the server it spawns.
// ---------------------------------------------------------------------------

class LspProcess {
  constructor(bin, args, opts) {
    this.child = cp.spawn(bin, args, { ...opts, stdio: ["pipe", "pipe", "pipe"] });
    this.buf = Buffer.alloc(0);
    this.nextId = 1;
    this.pending = new Map();
    this.notificationWaiters = [];
    this.stderr = "";
    this.child.stderr.on("data", (c) => {
      this.stderr += c.toString();
    });
    this.child.stdout.on("data", (c) => this._onData(c));
    this.child.on("error", (e) => {
      throw e;
    });
  }

  _onData(chunk) {
    this.buf = Buffer.concat([this.buf, chunk]);
    for (;;) {
      const headerEnd = this.buf.indexOf("\r\n\r\n");
      if (headerEnd < 0) return;
      const header = this.buf.slice(0, headerEnd).toString("utf8");
      const m = /Content-Length:\s*(\d+)/i.exec(header);
      if (!m) {
        // Malformed frame; drop what we have to avoid spinning forever.
        this.buf = Buffer.alloc(0);
        return;
      }
      const len = parseInt(m[1], 10);
      const bodyStart = headerEnd + 4;
      if (this.buf.length < bodyStart + len) return;
      const body = this.buf.slice(bodyStart, bodyStart + len).toString("utf8");
      this.buf = this.buf.slice(bodyStart + len);
      let msg;
      try {
        msg = JSON.parse(body);
      } catch (e) {
        continue;
      }
      this._dispatch(msg);
    }
  }

  _dispatch(msg) {
    if (msg.id !== undefined && this.pending.has(msg.id)) {
      const { resolve } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      resolve(msg);
      return;
    }
    if (msg.method) {
      if (process.env.SUGAR_LSP_E2E_DEBUG && msg.method !== "textDocument/publishDiagnostics") {
        console.log(`  [server notif] ${msg.method} ${JSON.stringify(msg.params).slice(0, 400)}`);
      }
      const remaining = [];
      for (const w of this.notificationWaiters) {
        if (w.pred(msg)) {
          w.resolve(msg);
        } else {
          remaining.push(w);
        }
      }
      this.notificationWaiters = remaining;
    }
  }

  _write(obj) {
    const body = JSON.stringify(obj);
    const frame = `Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`;
    this.child.stdin.write(frame, "utf8");
  }

  request(method, params) {
    const id = this.nextId++;
    return new Promise((resolve) => {
      this.pending.set(id, { resolve });
      this._write({ jsonrpc: "2.0", id, method, params });
    });
  }

  notify(method, params) {
    this._write({ jsonrpc: "2.0", method, params });
  }

  /** Wait for the next notification matching `pred`, with a timeout. */
  waitForNotification(pred, timeoutMs = 60_000) {
    return new Promise((resolve, reject) => {
      const w = { pred, resolve };
      this.notificationWaiters.push(w);
      const timer = setTimeout(() => {
        this.notificationWaiters = this.notificationWaiters.filter((x) => x !== w);
        reject(new Error(`timed out after ${timeoutMs}ms waiting for a ${pred.name || "notification"}`));
      }, timeoutMs);
      const origResolve = w.resolve;
      w.resolve = (msg) => {
        clearTimeout(timer);
        origResolve(msg);
      };
    });
  }

  kill() {
    try {
      this.child.kill("SIGKILL");
    } catch {
      /* already gone */
    }
  }
}

function publishDiagnosticsFor(uri) {
  const pred = (msg) =>
    msg.method === "textDocument/publishDiagnostics" && msg.params && msg.params.uri === uri;
  Object.defineProperty(pred, "name", { value: `publishDiagnostics(${uri})` });
  return pred;
}

(async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "sugar-lsp-e2e-"));
  console.log(`work dir: ${work}`);
  const { consumerDir, vendorDir, file } = stageConsumer(work, "flip");
  const uri = `file://${file}`;

  const env = { ...process.env, ...envFor(consumerDir, vendorDir) };
  const lsp = new LspProcess(LSP_BIN, ["--in-process"], { cwd: consumerDir, env });

  try {
    const initResp = await lsp.request("initialize", {
      processId: process.pid,
      rootUri: `file://${consumerDir}`,
      workspaceFolders: [{ uri: `file://${consumerDir}`, name: "consumer" }],
      capabilities: {},
    });
    check("initialize succeeds", !initResp.error, JSON.stringify(initResp.error));
    lsp.notify("initialized", {});

    // ---- didOpen the BAD text -> expect a red publishDiagnostics ----
    const badText = textWithLiteral("AAAA");
    const expLine = assertLine(badText);
    const badWait = lsp.waitForNotification(publishDiagnosticsFor(uri));
    lsp.notify("textDocument/didOpen", {
      textDocument: { uri, languageId: "python", version: 1, text: badText },
    });
    const badNotif = await badWait;
    const badDiags = badNotif.params.diagnostics || [];
    check("bad: a red diagnostic is published", badDiags.length > 0, JSON.stringify(badDiags));
    if (badDiags.length > 0) {
      const d = badDiags[0];
      console.log("  [bad] squiggle message:\n" + String(d.message).replace(/^/gm, "    "));
      check(
        "bad: anchored at the assert line",
        d.range && d.range.start && d.range.start.line === expLine - 1,
        `got ${d.range && d.range.start && d.range.start.line}, expected ${expLine - 1}`
      );
      check("bad: message carries Vendor fact", d.message.includes("Vendor fact:"), d.message);
      check("bad: message carries Vendor universe", d.message.includes("Vendor universe:"), d.message);
      check("bad: message carries Your fact", d.message.includes("Your fact:"), d.message);
      check("bad: message carries the UNSAT verdict", d.message.includes("UNSAT"), d.message);
    }

    // ---- didChange to the GOOD text -> diagnostics clear ----
    const goodText = textWithLiteral("eHl6");
    const clearWait = lsp.waitForNotification(publishDiagnosticsFor(uri));
    lsp.notify("textDocument/didChange", {
      textDocument: { uri, version: 2 },
      contentChanges: [{ text: goodText }],
    });
    const clearNotif = await clearWait;
    check(
      "good: diagnostics clear on the correct literal",
      (clearNotif.params.diagnostics || []).length === 0,
      JSON.stringify(clearNotif.params.diagnostics)
    );

    // ---- didChange back to the BAD text -> the diagnostic reappears ----
    const backWait = lsp.waitForNotification(publishDiagnosticsFor(uri));
    lsp.notify("textDocument/didChange", {
      textDocument: { uri, version: 3 },
      contentChanges: [{ text: badText }],
    });
    const backNotif = await backWait;
    check(
      "flip good->bad: the red diagnostic reappears",
      (backNotif.params.diagnostics || []).length > 0,
      JSON.stringify(backNotif.params.diagnostics)
    );

    await lsp.request("shutdown", null);
    lsp.notify("exit", null);
  } catch (e) {
    console.error("stderr so far:\n" + lsp.stderr);
    throw e;
  } finally {
    lsp.kill();
  }

  try {
    fs.rmSync(work, { recursive: true, force: true });
  } catch {
    /* best effort */
  }

  console.log("");
  if (failures > 0) {
    console.log(`==== lsp-e2e: FAIL (${failures}) ====`);
    process.exit(1);
  }
  console.log("==== lsp-e2e: PASS ====");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
