// SPDX-License-Identifier: MIT OR Apache-2.0
//
// prove-e2e.test.js: the IDE PROVE-path receipt (#3774 / #3779).
//
// It drives the SAME module the VS Code extension runs -- `proveClient` -- over
// the REAL demo fixtures (examples/python-base64-federation: native Python + a
// staged vendor `.proof`, NO annotations) and asserts T's flip:
//
//   consumer-bad  -> a RED diagnostic anchored at the `assert` line, carrying
//                    the `unsatisfied` reason (z3 returned unsat).
//   consumer-good -> no diagnostic.
//   flip the literal AAAA <-> eHl6 -> the diagnostic appears / clears.
//
// No VS Code host is needed: the diagnostics the editor would paint are exactly
// the array `proveProject` returns. `extension.ts` calls the same function, so
// this LSP-diagnostic-level test IS the receipt for the editor behavior.
//
// Env (set by run-prove-e2e.sh):
//   SUGAR_BIN                        resolved `sugar` binary (via bin/sugarbin)
//   SUGAR_PROVE_PATH                 PATH with the lifter's python on it
//   SUGAR_PROVE_PYTHONPATH_SUFFIX    the sugar-lift-py-* src roots
//   SUGAR_EXAMPLE_DIR                examples/python-base64-federation

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

// The env the lifter needs, with the consumer/vendor dir prepended to PYTHONPATH.
function envFor(consumerDir, vendorDir) {
  const suffix = process.env.SUGAR_PROVE_PYTHONPATH_SUFFIX || "";
  return {
    PATH: process.env.SUGAR_PROVE_PATH || process.env.PATH,
    PYTHONPATH: [consumerDir, vendorDir, suffix].filter(Boolean).join(path.delimiter),
  };
}

function run(binArgs, cwd, env) {
  const r = cp.spawnSync(BIN, binArgs, { cwd, env: { ...process.env, ...env }, encoding: "utf8" });
  if (r.status !== 0 && r.status !== null) {
    // mint must succeed; prove is driven through proveProject (red exit is fine there).
  }
  return r;
}

function mint(dir, vendorDir) {
  // Clean the dir's OWN prior proofs before re-minting (matches the example's
  // run.sh clean): a directory-prove reads every top-level `.proof`, so a stale
  // proof from an earlier literal would be conjoined alongside the new one and
  // read as a self-contradiction. Staged vendor imports live under
  // `.sugar/imports/` and are deliberately untouched.
  for (const n of fs.readdirSync(dir)) {
    if (/^blake3-512_.*\.proof$/.test(n)) {
      fs.rmSync(path.join(dir, n), { force: true });
    }
  }
  const runsDir = path.join(dir, ".sugar", "runs");
  fs.rmSync(runsDir, { recursive: true, force: true });
  const r = run(["mint", "--out", ".", "--quiet"], dir, envFor(dir, vendorDir));
  assert.strictEqual(r.status, 0, `mint failed in ${dir}: ${r.stderr || r.stdout}`);
}

function firstProof(dir) {
  const f = fs.readdirSync(dir).find((n) => /^blake3-512_.*\.proof$/.test(n));
  return f ? path.join(dir, f) : undefined;
}

// The `assert ... ==` line, computed from source (not a brittle constant).
function assertLine(file) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  return lines.findIndex((l) => l.includes("encodeBase64(") && l.includes("assert")) + 1;
}

// Build a hermetic copy of the example so we can flip literals without touching
// the committed fixtures, mint the vendor + one consumer, stage the .proof.
function stage(work, twin) {
  const src = EXAMPLE_DIR;
  const vendorDir = path.join(work, "vendor");
  const consumerDir = path.join(work, `consumer-${twin}`);
  fs.mkdirSync(vendorDir, { recursive: true });
  fs.mkdirSync(path.join(consumerDir, ".sugar", "imports"), { recursive: true });
  fs.copyFileSync(path.join(src, "vendor", "b64vendor.py"), path.join(vendorDir, "b64vendor.py"));
  fs.copyFileSync(
    path.join(src, `consumer-${twin}`, "test_consumer.py"),
    path.join(consumerDir, "test_consumer.py")
  );
  mint(vendorDir, vendorDir);
  const vproof = firstProof(vendorDir);
  assert(vproof, "vendor produced no .proof");
  fs.copyFileSync(vproof, path.join(consumerDir, ".sugar", "imports", path.basename(vproof)));
  // Mint the consumer AFTER its vendor import is staged, so the consumer's own
  // assertion contract exists in the proof the directory-prove will read.
  mint(consumerDir, vendorDir);
  return { consumerDir, vendorDir };
}

function proveConsumer(consumerDir, vendorDir) {
  return proveProject({
    binaryPath: BIN,
    projectDir: consumerDir,
    env: envFor(consumerDir, vendorDir),
  });
}

// Re-stamp the assertion's expected literal, then re-mint so the proof reflects it.
function setLiteral(consumerDir, vendorDir, literal) {
  const f = path.join(consumerDir, "test_consumer.py");
  const src = fs.readFileSync(f, "utf8");
  const next = src.replace(/== "[^"]*"/, `== "${literal}"`);
  fs.writeFileSync(f, next);
  // A fresh mint is the editor's "on save" step; imports are already staged.
  mint(consumerDir, vendorDir);
}

function consistencyDiag(res, consumerFile) {
  const base = path.basename(consumerFile);
  return res.diagnostics.find((d) => d.property.includes("xyz") && d.file.endsWith(base));
}

(async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "sugar-prove-e2e-"));
  console.log(`work dir: ${work}`);

  // ---- consumer-bad: the lie is UNSAT -> a red diagnostic at the assert line ----
  {
    const { consumerDir, vendorDir } = stage(work, "bad");
    const file = path.join(consumerDir, "test_consumer.py");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, vendorDir);
    console.log(`  [bad] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    const d = consistencyDiag(res, file);
    check("bad: a red diagnostic is emitted", !!d, JSON.stringify(res.diagnostics));
    if (d) {
      console.log(`  [bad] diagnostic: file=${d.file} line=${d.line} column=${d.column} status=${d.status}`);
      console.log(`  [bad] reason: ${d.reason}`);
      check("bad: status is unsatisfied", d.status === "unsatisfied", d.status);
      check("bad: anchored at the assert line", d.line === expLine, `got ${d.line}, expected ${expLine}`);
      check("bad: file is test_consumer.py", d.file.endsWith("test_consumer.py"), d.file);
      check(
        "bad: reason names the contradiction",
        /contradictory|unsat/i.test(d.reason),
        d.reason
      );
      // The squiggle message T's demo wants: the three conjoined facts as the
      // SAME human-readable FOL `sugar lift --report --visual` renders.
      const detail = formatDetail(d);
      console.log("  [bad] squiggle message:\n" + detail.replace(/^/gm, "    "));
      check(
        "bad: VENDOR UNIVERSE renders the str.eq-bv-blocks universe FOL",
        typeof d.vendorUniverseFol === "string" && d.vendorUniverseFol.includes("str.eq-bv-blocks"),
        d.vendorUniverseFol
      );
      check(
        "bad: YOUR FACT renders the consumer's own equality with its literal",
        typeof d.clientFactFol === "string" &&
          /call:(?:[\w.]+\.)?encodeBase64\("xyz"\)/.test(d.clientFactFol) &&
          d.clientFactFol.includes('"AAAA"'),
        d.clientFactFol
      );
      // VENDOR FACT (derived): the universe carries no sworn vector, so the
      // vendor's fact for this callsite is the law instantiated at "xyz" ->
      // z3.model derives "eHl6". It must show as its OWN labeled line.
      check(
        "bad: VENDOR FACT renders the DERIVED vendor value (eHl6), not the lie",
        typeof d.vendorFactFol === "string" &&
          /call:(?:[\w.]+\.)?encodeBase64\("xyz"\)/.test(d.vendorFactFol) &&
          d.vendorFactFol.includes('"eHl6"') &&
          !d.vendorFactFol.includes('"AAAA"'),
        d.vendorFactFol
      );
      check(
        "bad: the squiggle shows all 4 labeled lines + the conjoined verdict",
        detail.includes("Vendor fact:") &&
          detail.includes('"eHl6"') &&
          detail.includes("Vendor universe:") &&
          detail.includes("str.eq-bv-blocks") &&
          detail.includes("Your fact:") &&
          detail.includes('"AAAA"') &&
          detail.includes("Conjoined:") &&
          detail.includes("∧") &&
          detail.includes("UNSAT"),
        detail
      );
    }
    check("bad: red gate exit code", res.exitCode !== 0, `exit ${res.exitCode}`);

    // ---- flip the literal to the CORRECT base64 -> the diagnostic clears ----
    setLiteral(consumerDir, vendorDir, "eHl6");
    const res2 = await proveConsumer(consumerDir, vendorDir);
    console.log(`  [bad->fixed] prove latency: ${res2.elapsedMs}ms  exit=${res2.exitCode}`);
    check(
      "flip bad->correct: diagnostic clears",
      !consistencyDiag(res2, file),
      JSON.stringify(res2.diagnostics)
    );
  }

  // ---- consumer-good: correct base64 -> no diagnostic ----
  {
    const { consumerDir, vendorDir } = stage(work, "good");
    const file = path.join(consumerDir, "test_consumer.py");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, vendorDir);
    console.log(`  [good] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    check("good: no red diagnostic", !consistencyDiag(res, file), JSON.stringify(res.diagnostics));

    // ---- flip the literal to a LIE -> a red diagnostic appears at the assert line ----
    setLiteral(consumerDir, vendorDir, "AAAA");
    const res2 = await proveConsumer(consumerDir, vendorDir);
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
    console.log(`==== prove-e2e: FAIL (${failures}) ====`);
    process.exit(1);
  }
  console.log("==== prove-e2e: PASS ====");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
