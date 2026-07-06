// SPDX-License-Identifier: MIT OR Apache-2.0
//
// e2e.test.js: the slice A receipt (#3774).
//
// It speaks the sugar-linkerd wire protocol end to end — the same
// `LinkerdClient` the VS Code extension uses — and asserts T's flip:
//   1. open a document in the LYING state  -> a RED diagnostic arrives, with a
//      real range (line/column) and the linker's reason text;
//   2. edit it to the TRUTHFUL state       -> the diagnostic clears.
//
// No GUI / VS Code host is needed: the diagnostics the editor would paint are
// exactly the array this test asserts on. A full editor E2E is not possible
// headlessly in CI, so this LSP-protocol-level test IS the receipt.
//
// The daemon binary is resolved by run-e2e.sh (via bin/sugarbin) and passed in
// SUGAR_LINKERD_BIN. The `rust` kit is used because its lifter runs in-process
// inside the daemon — no external kit binary is required, so the receipt is
// hermetic.

const assert = require("assert");
const os = require("os");
const path = require("path");
const fs = require("fs");

const { LinkerdClient } = require("../out/linkerdClient.js");

const BIN = process.env.SUGAR_LINKERD_BIN;
const FIXTURES = path.join(__dirname, "fixtures");

async function main() {
  assert.ok(BIN, "SUGAR_LINKERD_BIN must point at the sugar-linkerd binary");
  assert.ok(fs.existsSync(BIN), `sugar-linkerd binary not found at ${BIN}`);

  const tag = `sugar-e2e-${process.pid}`;
  const socketPath = path.join(os.tmpdir(), `${tag}.sock`);
  const snapshotPath = path.join(os.tmpdir(), `${tag}.snapshot`);
  const client = new LinkerdClient(socketPath);

  // The editor sends the absolute path of the open document. Using an absolute
  // path here is load-bearing: it is exactly the case the daemon path-mapping
  // fix in this change repairs (basename loci silently dropped every diagnostic).
  const docPath = path.join(os.tmpdir(), `${tag}-test_index.rs`);
  const redSource = fs.readFileSync(path.join(FIXTURES, "red.rs"), "utf8");
  const greenSource = fs.readFileSync(path.join(FIXTURES, "green.rs"), "utf8");
  // 1-based line of the call site, computed from the fixture so the assertion
  // is not a brittle hardcoded number.
  const expectedLine =
    redSource
      .split("\n")
      .findIndex((l) => l.includes("checked_index(7)") && !l.trimStart().startsWith("//")) + 1;

  let failures = 0;
  const check = (name, cond, detail) => {
    if (cond) {
      console.log(`ok   - ${name}`);
    } else {
      failures++;
      console.log(`FAIL - ${name}${detail ? ` :: ${detail}` : ""}`);
    }
  };

  try {
    await client.ensureDaemon(BIN, snapshotPath);

    // ---- 1. LYING assertion -> RED. ----
    const red = await client.parseFile("rust", docPath, redSource);
    check("red: exactly one diagnostic", red.length === 1, `got ${red.length}`);
    const d = red[0] || {};
    check(
      "red: production error kind is a discharge refusal",
      d.errorKind === "implication-undecidable",
      d.errorKind
    );
    check(
      "red: carries the linker's reason text",
      typeof d.reason === "string" && /post_caller|pre_callee|discharge/.test(d.reason),
      d.reason
    );
    check(
      "red: diagnostic file matches the absolute document path",
      d.file === docPath,
      `${d.file} !== ${docPath}`
    );
    const line = d.callSiteLocus && d.callSiteLocus.line;
    check(
      "red: has a real call-site line (range to anchor the squiggle)",
      typeof line === "number" && line > 0,
      JSON.stringify(d.callSiteLocus)
    );
    check(
      "red: locus points at the checked_index(7) call line",
      line === expectedLine,
      `line=${line} (expected ${expectedLine})`
    );

    // ---- 2. Correct it -> GREEN. ----
    const green = await client.parseFile("rust", docPath, greenSource);
    check("green: diagnostic clears", green.length === 0, `got ${green.length}`);

    // ---- 3. Flip back -> RED again (green->red direction of the bar). ----
    const redAgain = await client.parseFile("rust", docPath, redSource);
    check("green->red: the squiggle returns", redAgain.length === 1, `got ${redAgain.length}`);
  } finally {
    await client.shutdown();
  }

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed`);
    process.exit(1);
  }
  console.log("\nslice A receipt: red -> green -> red verified through sugar-linkerd");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
