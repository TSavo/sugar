// SPDX-License-Identifier: MIT OR Apache-2.0
//
// linkerdClient.ts: a dependency-free (no `vscode` import) client for the
// sugar-linkerd daemon wire protocol, so the exact same code path is exercised
// by the editor extension AND the headless end-to-end receipt.
//
// Wire protocol (spec #126 §3, as exercised by
// implementations/rust/sugar-linkerd/tests/conformance.rs):
//   - Newline-delimited JSON-RPC 2.0 over a Unix domain socket.
//   - One request line in, one response line out; the daemon also serves
//     concurrent connections, so we open a fresh connection per request.
//   - parseFile { kitId, file, source } -> { diagnostics: LinkerDiagnostic[] }
//   - projectStatus {} / shutdown {} are used for readiness / teardown.

import * as net from "net";
import * as fs from "fs";
import * as cp from "child_process";

/** One diagnostic as returned by sugar-linkerd's `parseFile`. */
export interface LinkerDiagnostic {
  kind: string;
  errorKind: string;
  targetSymbol: string;
  sourceContractCid: string;
  reason: string;
  file: string | null;
  callSiteLocus: {
    file?: string;
    line?: number | null;
    column?: number | null;
  } | null;
}

/**
 * One row as returned by sugar-linkerd's `proveConsistency` (#3774
 * warm-daemon slice), the SAME JSON shape `sugar prove --json` renders (both
 * go through `sugar_verifier::report::row_to_json`).
 */
export interface ProveRow {
  bridge: string | null;
  property: string | null;
  propertyCid: string | null;
  status: string;
  reason: string;
  dischargeMethod: string | null;
  bodyDischargeTier: string | null;
  verification: unknown;
  file: string | null;
  line: number | null;
}

/** Error codes the daemon can return for `proveConsistency`. */
export const ERR_PROVE_CONTEXT_UNAVAILABLE = -33004;
export const ERR_METHOD_NOT_FOUND = -32601;

/** Map a source file extension to the kitId sugar-linkerd dispatches on. */
export function kitIdForFile(file: string): string | undefined {
  const dot = file.lastIndexOf(".");
  const ext = dot >= 0 ? file.slice(dot + 1).toLowerCase() : "";
  const table: Record<string, string> = {
    rs: "rust",
    py: "python",
    go: "go",
    cs: "csharp",
    rb: "ruby",
    zig: "zig",
    java: "java",
    swift: "swift",
    cpp: "cpp",
    cc: "cpp",
    c: "c",
    php: "php",
    scala: "scala",
  };
  return table[ext];
}

/** A live handle to a sugar-linkerd daemon reachable at a Unix socket. */
export class LinkerdClient {
  private nextId = 1;
  private child: cp.ChildProcess | undefined;

  constructor(private readonly socketPath: string) {}

  /**
   * Ensure a daemon is reachable at `socketPath`. If it is not and a
   * `binaryPath` is supplied, spawn one and wait for the socket to answer.
   */
  async ensureDaemon(
    binaryPath: string | undefined,
    snapshotPath: string,
    idleTimeoutMs = 600_000,
    extraArgs: string[] = []
  ): Promise<void> {
    if (await this.isLive()) {
      return;
    }
    if (!binaryPath) {
      throw new Error(
        `no sugar-linkerd at ${this.socketPath} and no binaryPath configured ` +
          `(resolve one with: bin/sugarbin --bin sugar-linkerd)`
      );
    }
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* socket absent: fine */
    }
    this.child = cp.spawn(
      binaryPath,
      [
        "--socket",
        this.socketPath,
        "--snapshot",
        snapshotPath,
        "--idle-timeout-ms",
        String(idleTimeoutMs),
        ...extraArgs,
      ],
      { stdio: "ignore" }
    );
    this.child.unref();
    await this.waitForSocket(10_000);
  }

  /** Read the daemon's status/capabilities (includes `solverMode`). */
  async projectStatus(): Promise<any> {
    const res = await this.rpc("projectStatus", {});
    if (res.error) {
      throw new LinkerdRpcError(res.error.code, res.error.message);
    }
    return res.result ?? {};
  }

  private async isLive(): Promise<boolean> {
    if (!fs.existsSync(this.socketPath)) {
      return false;
    }
    try {
      await this.rpc("projectStatus", {});
      return true;
    } catch {
      return false;
    }
  }

  private async waitForSocket(timeoutMs: number): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (fs.existsSync(this.socketPath)) {
        try {
          await this.rpc("projectStatus", {});
          return;
        } catch {
          /* not ready yet */
        }
      }
      await delay(50);
    }
    throw new Error(`sugar-linkerd socket ${this.socketPath} never became ready`);
  }

  /** Send a `parseFile` and return the diagnostics for this file. */
  async parseFile(
    kitId: string,
    file: string,
    source: string
  ): Promise<LinkerDiagnostic[]> {
    const res = await this.rpc("parseFile", { kitId, file, source });
    if (res.error) {
      throw new LinkerdRpcError(res.error.code, res.error.message);
    }
    const diags = res.result?.diagnostics;
    return Array.isArray(diags) ? (diags as LinkerDiagnostic[]) : [];
  }

  /**
   * Send a `proveConsistency` request and return the rows. This is the warm
   * path (#3774 warm-daemon slice): the daemon runs `verify_consistency`
   * against its resident pool/plan/registry (built once at startup), instead
   * of a cold `sugar prove` shell re-loading the whole proof catalog per
   * save. Throws `LinkerdRpcError` (code `ERR_PROVE_CONTEXT_UNAVAILABLE` or
   * `ERR_METHOD_NOT_FOUND` for an older daemon) on failure — callers should
   * treat that identically to "daemon down" and fall back to a cold path.
   *
   * NAMED GAP: as of this slice the daemon verifies its resident on-disk
   * pool, not `source` (the unsaved buffer) — see
   * `sugar-linkerd/src/methods.rs::handle_prove_consistency` doc comment.
   * `source` is still sent so the wire shape matches `parseFile` and no
   * second RPC shape is needed once lift-and-merge lands.
   */
  async proveConsistency(
    kitId: string,
    file: string,
    source: string
  ): Promise<ProveRow[]> {
    const res = await this.rpc("proveConsistency", { kitId, file, source });
    if (res.error) {
      throw new LinkerdRpcError(res.error.code, res.error.message);
    }
    const rows = res.result?.rows;
    return Array.isArray(rows) ? (rows as ProveRow[]) : [];
  }

  /** Best-effort daemon shutdown (used by tests). */
  async shutdown(): Promise<void> {
    try {
      await this.rpc("shutdown", {});
    } catch {
      /* daemon may already be gone */
    }
    if (this.child && !this.child.killed) {
      this.child.kill();
    }
  }

  /** One request line in, one response line out, fresh connection. */
  private rpc(method: string, params: unknown): Promise<any> {
    const id = this.nextId++;
    const req = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      const conn = net.connect(this.socketPath);
      let buf = "";
      let settled = false;
      const done = (fn: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        conn.end();
        fn();
      };
      conn.on("connect", () => conn.write(JSON.stringify(req) + "\n"));
      conn.on("data", (chunk) => {
        buf += chunk.toString();
        const nl = buf.indexOf("\n");
        if (nl >= 0) {
          const line = buf.slice(0, nl);
          done(() => {
            try {
              resolve(JSON.parse(line));
            } catch (e) {
              reject(e);
            }
          });
        }
      });
      conn.on("error", (e) => done(() => reject(e)));
    });
  }
}

export class LinkerdRpcError extends Error {
  constructor(public readonly code: number, message: string) {
    super(message);
    this.name = "LinkerdRpcError";
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
