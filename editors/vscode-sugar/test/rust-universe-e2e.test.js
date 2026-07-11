// SPDX-License-Identifier: MIT OR Apache-2.0
//
// rust-universe-e2e.test.js: the IDE PROVE-path receipt for the rust CASE 2
// squiggle (#3774) -- a vendor UNIVERSE (a lifted bounded-loop law), not a
// stated vector, deciding the consumer's claim.
//
// It drives the SAME module the VS Code extension runs -- `proveClient` --
// over the REAL fixture (examples/rust-forall-universe-federation: a rust
// vendor crate whose ONLY testimony about x=3 / x=5 is the lifted universe
// `forall x in 0..8. block_width(x) == 64`, staged .proof, NO annotations)
// and asserts the rust parity of the python base64 demo's crown moment:
//
//   consumer-bad  (assert_eq!(block_width(3), 128)) -> RED diagnostic anchored
//                 at the assert line in the CONSUMER's OWN
//                 tests/consumer_test.rs, whose squiggle carries
//                   Vendor fact:     block_width(3) = 64   <- the vendor's
//                                    value AT THE CONSUMER'S OWN ARGUMENT,
//                                    projected from the conjoined universe
//                                    (no vendor assertion ever named x=3)
//                   Vendor universe: forall _level. block_width(_level) = 64
//                   Your fact:       block_width(3) = 128
//                   Conjoined:       ... -> UNSAT
//   consumer-good (assert_eq!(block_width(5), 64))  -> no diagnostic (the
//                 universe is independent-KIND testimony: the true point
//                 DISCHARGES, #3445 Part-2 ruling).
//   flip the literal 128 <-> 64 -> the diagnostic appears / clears.
//
// Env (set by run-rust-universe-e2e.sh):
//   SUGAR_BIN           resolved `sugar` binary (via bin/sugarbin)
//   SUGAR_EXAMPLE_DIR   examples/rust-forall-universe-federation

const assert = require("assert");
const os = require("os");
const path = require("path");
const fs = require("fs");
const cp = require("child_process");

const { proveProject, formatDetail } = require("../out/proveClient.js");

const BIN = process.env.SUGAR_BIN;
const EXAMPLE_DIR = process.env.SUGAR_EXAMPLE_DIR;
assert(BIN && fs.existsSync(BIN), `SUGAR_BIN must point at a sugar binary (got ${BIN})`);
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

function run(binArgs, cwd, env) {
  return cp.spawnSync(BIN, binArgs, { cwd, env: { ...process.env, ...env }, encoding: "utf8" });
}

function mint(dir, env) {
  for (const n of fs.readdirSync(dir)) {
    if (/^blake3-512_.*\.proof$/.test(n)) {
      fs.rmSync(path.join(dir, n), { force: true });
    }
  }
  fs.rmSync(path.join(dir, ".sugar", "runs"), { recursive: true, force: true });
  const r = run(["mint", "--out", ".", "--quiet"], dir, env);
  assert.strictEqual(r.status, 0, `mint failed in ${dir}: ${r.stderr || r.stdout}`);
}

// Same hermetic registry as rust-prove-e2e.test.js (see that file for WHY).
function writeComponentRegistry(work, binDir) {
  const dir = path.join(work, "components");
  const entries = {
    "rust-walk": [path.join(binDir, "sugar-walk-rpc"), "--rpc"],
    "rust-test-assertions": [path.join(binDir, "rust_test_assertions_rpc")],
    "rust-cargo-test-witness": [path.join(binDir, "witness_rpc")],
    "ir-compiler-smt-lib": [path.join(binDir, "sugar-ir-smt-lib")],
  };
  for (const [name, command] of Object.entries(entries)) {
    const compDir = path.join(dir, name);
    fs.mkdirSync(compDir, { recursive: true });
    const arr = command.map((t) => `"${t}"`).join(", ");
    fs.writeFileSync(
      path.join(compDir, "manifest.toml"),
      `name = "${name}"\nversion = "0.1.0"\nprotocol_version = "sugar-component/1"\ncommand = [${arr}]\n`
    );
  }
  return dir;
}

function firstProof(dir) {
  const f = fs.readdirSync(dir).find((n) => /^blake3-512_.*\.proof$/.test(n));
  return f ? path.join(dir, f) : undefined;
}

// The `assert_eq!(block_width(...)` line, computed from source.
function assertLine(file) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  return lines.findIndex((l) => l.includes("assert_eq!(block_width(")) + 1;
}

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "target") continue; // never copy build output
      copyDir(s, d);
    } else {
      fs.copyFileSync(s, d);
    }
  }
}

function templateManifests(dir, binDir) {
  for (const surface of ["rust-test-assertions", "rust-cargo-test-witness"]) {
    const src = path.join(dir, ".sugar", "lift", surface, "manifest.toml.in");
    const dst = path.join(dir, ".sugar", "lift", surface, "manifest.toml");
    const text = fs.readFileSync(src, "utf8").replace(/@BIN_DIR@/g, binDir);
    fs.writeFileSync(dst, text);
  }
}

// Hermetic copy of the fixture; the consumer crates depend on the vendor by
// relative path (`../vendor`), so vendor + consumer travel together.
function stage(work, twin, binDir, componentPath) {
  const src = EXAMPLE_DIR;
  const vendorDir = path.join(work, "vendor");
  const consumerDir = path.join(work, `consumer-${twin}`);
  copyDir(path.join(src, "vendor"), vendorDir);
  copyDir(path.join(src, `consumer-${twin}`), consumerDir);
  templateManifests(vendorDir, binDir);
  templateManifests(consumerDir, binDir);
  fs.mkdirSync(path.join(consumerDir, ".sugar", "imports"), { recursive: true });

  const env = { SUGAR_COMPONENT_PATH: componentPath };
  mint(vendorDir, env);
  const vproof = firstProof(vendorDir);
  assert(vproof, "vendor produced no .proof");
  fs.copyFileSync(vproof, path.join(consumerDir, ".sugar", "imports", path.basename(vproof)));
  mint(consumerDir, env);
  return { consumerDir, vendorDir, env };
}

function proveConsumer(consumerDir, env) {
  return proveProject({ binaryPath: BIN, projectDir: consumerDir, env });
}

// Re-stamp the asserted literal at the consumer's callsite, then re-mint.
function setLiteral(consumerDir, literal, env) {
  const f = path.join(consumerDir, "tests", "consumer_test.rs");
  const src = fs.readFileSync(f, "utf8");
  const next = src.replace(
    /assert_eq!\(block_width\((\d+)\), \d+\);/,
    `assert_eq!(block_width($1), ${literal});`
  );
  fs.writeFileSync(f, next);
  mint(consumerDir, env);
}

function consistencyDiag(res, consumerFile) {
  const base = path.basename(consumerFile);
  return res.diagnostics.find(
    (d) =>
      d.property.includes("block_width#euf#") &&
      !d.property.includes("panic_callsite") &&
      d.file.endsWith(base)
  );
}

(async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "sugar-rust-universe-e2e-"));
  console.log(`work dir: ${work}`);
  const binDir = path.dirname(BIN);
  const componentPath = writeComponentRegistry(work, binDir);

  // ---- consumer-bad: the lie about an un-named point is UNSAT ----
  {
    const { consumerDir, env } = stage(work, "bad", binDir, componentPath);
    const file = path.join(consumerDir, "tests", "consumer_test.rs");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, env);
    console.log(`  [bad] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    const d = consistencyDiag(res, file);
    check("bad: a red diagnostic is emitted", !!d, JSON.stringify(res.diagnostics));
    if (d) {
      console.log(`  [bad] diagnostic: file=${d.file} line=${d.line} column=${d.column} status=${d.status}`);
      console.log(`  [bad] reason: ${d.reason}`);
      check("bad: status is unsatisfied", d.status === "unsatisfied", d.status);
      check("bad: anchored at the assert line", d.line === expLine, `got ${d.line}, expected ${expLine}`);
      check(
        "bad: file is the CONSUMER's own tests/consumer_test.rs",
        d.file.endsWith("tests/consumer_test.rs"),
        d.file
      );
      const detail = formatDetail(d);
      console.log("  [bad] squiggle message:\n" + detail.replace(/^/gm, "    "));
      check(
        "bad: VENDOR UNIVERSE renders the quantified law (∀ ... block_width(_level) = 64)",
        typeof d.vendorUniverseFol === "string" &&
          d.vendorUniverseFol.includes("∀") &&
          d.vendorUniverseFol.includes("block_width(_level) = 64"),
        d.vendorUniverseFol
      );
      check(
        "bad: VENDOR FACT is the universe AT THE CONSUMER'S OWN ARGUMENT (x=3, never sworn point-wise)",
        typeof d.vendorFactFol === "string" && d.vendorFactFol.includes("block_width(3) = 64"),
        d.vendorFactFol
      );
      check(
        "bad: YOUR FACT renders the consumer's lie",
        typeof d.clientFactFol === "string" && d.clientFactFol.includes("block_width(3) = 128"),
        d.clientFactFol
      );
      check(
        "bad: the squiggle shows all three labeled lines + the conjoined UNSAT verdict",
        detail.includes("Vendor fact:") &&
          detail.includes("Vendor universe:") &&
          detail.includes("Your fact:") &&
          detail.includes("Conjoined:") &&
          detail.includes("∧") &&
          detail.includes("UNSAT"),
        detail
      );
    }
    check("bad: red gate exit code", res.exitCode !== 0, `exit ${res.exitCode}`);

    // ---- flip the literal to the CORRECT value -> the diagnostic clears ----
    setLiteral(consumerDir, "64", env);
    const res2 = await proveConsumer(consumerDir, env);
    console.log(`  [bad->fixed] prove latency: ${res2.elapsedMs}ms  exit=${res2.exitCode}`);
    check(
      "flip bad->correct: diagnostic clears",
      !consistencyDiag(res2, file),
      JSON.stringify(res2.diagnostics)
    );
  }

  // ---- consumer-good: the TRUE un-named point -> no diagnostic ----
  {
    const { consumerDir, env } = stage(work, "good", binDir, componentPath);
    const file = path.join(consumerDir, "tests", "consumer_test.rs");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, env);
    console.log(`  [good] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    check("good: no red diagnostic", !consistencyDiag(res, file), JSON.stringify(res.diagnostics));
    const goodRow = res.rows.find(
      (r) =>
        typeof r.property === "string" &&
        r.property.includes("block_width#euf#") &&
        !r.property.includes("panic_callsite") &&
        typeof r.file === "string" &&
        r.file.endsWith("tests/consumer_test.rs")
    );
    check(
      "good: the true un-named point is DISCHARGED by the universe (independent-KIND witness)",
      !!goodRow && goodRow.status === "discharged",
      goodRow && goodRow.status
    );

    // ---- flip the literal to a LIE -> a red diagnostic appears ----
    setLiteral(consumerDir, "128", env);
    const res2 = await proveConsumer(consumerDir, env);
    console.log(`  [good->lie] prove latency: ${res2.elapsedMs}ms  exit=${res2.exitCode}`);
    const d = consistencyDiag(res2, file);
    check("flip correct->lie: a red diagnostic appears", !!d, JSON.stringify(res2.diagnostics));
    if (d) {
      console.log(`  [good->lie] diagnostic: file=${d.file} line=${d.line} column=${d.column} status=${d.status}`);
      check("flip: anchored at the assert line", d.line === expLine, `got ${d.line}, expected ${expLine}`);
    }
  }

  try {
    fs.rmSync(work, { recursive: true, force: true });
  } catch {
    /* best effort */
  }

  console.log("");
  if (failures > 0) {
    console.log(`==== rust-universe-e2e: FAIL (${failures}) ====`);
    process.exit(1);
  }
  console.log("==== rust-universe-e2e: PASS ====");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
