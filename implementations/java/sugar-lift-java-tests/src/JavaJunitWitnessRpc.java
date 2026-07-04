// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Java-native JUnit witness kit for the Sugar/ProvekIt substrate.
// P5a: the witness lifter role — LIFT + RESOLVE_WITNESS.
//
// THE ROLE: at LIFT time this is the PRODUCER: it scans a Java project for
// test methods (named test* or annotated @Test by type name), RUNS them,
// builds a content-addressed bundle (one JSON line per test, sorted by test
// id, each body JCS-serialized), and emits a ContractDecl carrying the
// witness evidence plus a WitnessPackageMemento. At RESOLVE time it is the
// ORACLE: it re-runs the suite and returns the bundle bytes base64-encoded.
// The rust verifier recomputes blake3 of those bytes itself — the kit is
// UNTRUSTED, never decides the verdict.
//
// Wire protocol: NDJSON JSON-RPC 2.0, one request per stdin line, one
// reply per stdout line. Handles: initialize, sugar.plugin.kit_declaration,
// lift, sugar.plugin.resolve_witness, shutdown.
//
// JDK-ONLY: javax.tools.JavaCompiler + reflection. No external jars.
// Compiles with -source 21 -target 21. blake3-512 XOF to 64 bytes
// implemented in pure Java matching the BLAKE3 spec exactly.
//
// WITNESS BODY FORMAT (kind="junit-test-witness"):
//   Each test line = JCS({"codeCid":..., "codeFiles":...,
//                          "kind":"junit-test-witness",
//                          "outcome":"passed"|"failed",
//                          "runtimeCid":..., "test":...})
//   Bundle bytes = concat(line + "\n") over tests sorted by test id.
//   Bundle CID = "blake3-512:" + lowercase-hex(blake3_xof_64(bundle_bytes))
//
// TEST DISCOVERY (JDK-only, no JUnit runtime):
//   Compiles Java source files found under src/ or test/ or tests/ in the
//   project dir. Invokes methods annotated @org.junit.jupiter.api.Test,
//   @org.junit.Test, or named with prefix "test" (no args, public).
//   A method that returns without throwing = "passed"; any Throwable = "failed".

import javax.tools.*;
import java.io.*;
import java.math.BigInteger;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public final class JavaJunitWitnessRpc {

    private static final String KIT_ID         = "java-junit-witness";
    private static final String SURFACE        = "java-junit-witness";
    private static final String VERSION        = "0.1.0";
    private static final String RESOLVE_METHOD = "sugar.plugin.resolve_witness";
    private static final String DEP_PROOF_METHOD = "sugar.plugin.resolve_dependency_proofs";
    private static final String KIT_DECL       = "sugar.plugin.kit_declaration";

    // ── Entry point ────────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {
        BufferedReader in  = new BufferedReader(
            new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintWriter    out = new PrintWriter(
            new OutputStreamWriter(System.out, StandardCharsets.UTF_8), true);
        String line;
        while ((line = in.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            String reply = handle(line);
            if (reply != null) out.println(reply);
            // shutdown is signalled by handle() returning null
            if (reply == null) break;
        }
    }

    // ── Dispatcher ─────────────────────────────────────────────────────────────

    private static String handle(String req) {
        String id     = extractId(req);
        String method = jsonString(req, "method");
        try {
            return switch (method) {
                case "initialize"    -> ok(id, initializeResult());
                case KIT_DECL        -> ok(id, kitDeclarationResult());
                case "lift"          -> ok(id, lift(req));
                case RESOLVE_METHOD  -> ok(id, resolveWitness(req));
                case DEP_PROOF_METHOD -> ok(id,
                        JavaDependencyProofResolver.resolveDependencyProofs(req));
                case "shutdown", "sugar.plugin.shutdown" -> {
                    System.out.println("{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":null}");
                    System.out.flush();
                    yield null; // signals main() to stop
                }
                default -> error(id, -32601, "unknown method: " + method);
            };
        } catch (Exception e) {
            return error(id, -32603, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    // ── JSON-RPC wire helpers ──────────────────────────────────────────────────

    private static String ok(String id, String resultJson) {
        return "{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":" + resultJson + "}";
    }

    private static String error(String id, int code, String msg) {
        return "{\"jsonrpc\":\"2.0\",\"id\":" + id
             + ",\"error\":{\"code\":" + code
             + ",\"message\":" + jsl(msg) + "}}";
    }

    /** Extract raw id token (number, string, or null) from a JSON-RPC line. */
    static String extractId(String json) {
        int i = json.indexOf("\"id\"");
        if (i < 0) return "null";
        int colon = json.indexOf(':', i + 4);
        if (colon < 0) return "null";
        int s = colon + 1;
        while (s < json.length() && json.charAt(s) == ' ') s++;
        if (s >= json.length()) return "null";
        if (json.charAt(s) == '"') {
            int e = json.indexOf('"', s + 1);
            return e < 0 ? "null" : json.substring(s, e + 1);
        }
        int e = s;
        while (e < json.length() && ",}] ".indexOf(json.charAt(e)) < 0) e++;
        String tok = json.substring(s, e).trim();
        return tok.isEmpty() ? "null" : tok;
    }

    /**
     * Extract the first string value for a key anywhere in the JSON line
     * (shallow scan sufficient for the flat-ish RPC messages we receive).
     */
    static String jsonString(String json, String key) {
        String needle = "\"" + key + "\"";
        int i = json.indexOf(needle);
        if (i < 0) return "";
        int colon = json.indexOf(':', i + needle.length());
        if (colon < 0) return "";
        int s = colon + 1;
        while (s < json.length() && json.charAt(s) == ' ') s++;
        if (s >= json.length() || json.charAt(s) != '"') return "";
        StringBuilder sb = new StringBuilder();
        int j = s + 1;
        while (j < json.length()) {
            char c = json.charAt(j);
            if (c == '\\' && j + 1 < json.length()) {
                char n = json.charAt(j + 1);
                switch (n) {
                    case '"'  -> { sb.append('"');  j += 2; }
                    case '\\' -> { sb.append('\\'); j += 2; }
                    case 'n'  -> { sb.append('\n'); j += 2; }
                    case 'r'  -> { sb.append('\r'); j += 2; }
                    case 't'  -> { sb.append('\t'); j += 2; }
                    default   -> { sb.append(n);    j += 2; }
                }
            } else if (c == '"') {
                break;
            } else {
                sb.append(c);
                j++;
            }
        }
        return sb.toString();
    }

    /** JSON-string-literal encode (jsl = json string literal). */
    static String jsl(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if      (c == '"')  sb.append("\\\"");
            else if (c == '\\') sb.append("\\\\");
            else if (c < 0x20)  sb.append(String.format("\\u%04x", (int) c));
            else                sb.append(c);
        }
        return sb.append('"').toString();
    }

    static String jsonArray(List<String> items) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) sb.append(',');
            sb.append(jsl(items.get(i)));
        }
        return sb.append(']').toString();
    }

    // ── Protocol results ───────────────────────────────────────────────────────

    private static String initializeResult() {
        return "{\"name\":\"sugar-lift-java-junit-witness\","
             + "\"version\":\"" + VERSION + "\","
             + "\"protocol_version\":\"pep/1.7.0\","
             + "\"capabilities\":{"
             + "\"authoring_surfaces\":[\"" + SURFACE + "\"],"
             + "\"ir_version\":\"v1.1.0\","
             + "\"emits_signed_mementos\":false}}";
    }

    private static String kitDeclarationResult() {
        return "{\"kit\":{\"id\":\"" + KIT_ID + "\",\"language\":\"java\","
             + "\"version\":\"" + VERSION + "\"},"
             + "\"rpc\":{\"methods\":["
             + "{\"name\":\"initialize\",\"required\":true},"
             + "{\"name\":\"" + KIT_DECL + "\",\"required\":true},"
             + "{\"name\":\"lift\",\"required\":true},"
             + "{\"name\":\"" + DEP_PROOF_METHOD + "\",\"required\":false},"
             + "{\"name\":\"" + RESOLVE_METHOD + "\",\"required\":false},"
             + "{\"name\":\"shutdown\",\"required\":false}"
             + "]},"
             + "\"proofResolution\":{\"strategy\":\"maven\","
             + "\"rpcMethod\":\"" + DEP_PROOF_METHOD + "\"},"
             + "\"effectKinds\":[],\"effectLeaves\":[],\"guardPredicates\":[],"
             + "\"controlCarriers\":[],\"residueCategories\":[]}";
    }

    // ── LIFT ───────────────────────────────────────────────────────────────────

    private static String lift(String req) throws Exception {
        String wsRoot = jsonString(req, "workspace_root");
        if (wsRoot.isEmpty()) wsRoot = ".";
        Path dir = Path.of(wsRoot);

        LiftResult lr = runAndBuildBundle(dir);

        String proofData = buildProofData(
            lr.bundleCid, lr.testFiles, lr.codeFiles, lr.count, lr.passed);
        String contractIr = buildContractIr(
            lr.bundleCid, lr.runtimeCid, proofData);
        String memento = buildMemento(
            lr.bundleCid, lr.testFiles, lr.codeFiles, lr.count, lr.passed);

        // Write bundle to .sugar/witnesses/ (audit; never fail lift on I/O error)
        try {
            Path wdir = dir.resolve(".sugar").resolve("witnesses");
            Files.createDirectories(wdir);
            Files.write(wdir.resolve(lr.bundleCid.replace(":", "_") + ".witness"),
                        lr.bundleBytes);
        } catch (Exception ignored) {}

        // The memento rides in BOTH `ir` and `witness_mementos`, mirroring the
        // rust cargo-test-witness kit: mint iterates ONLY the `ir` array and
        // dispatches on each decl's `kind`, so a witness-memento that lives only
        // in `witness_mementos` is silently dropped (no witness dimension).
        return "{\"kind\":\"ir-document\","
             + "\"ir\":[" + contractIr + "," + memento + "],"
             + "\"witness_mementos\":[" + memento + "],"
             + "\"implications\":[],"
             + "\"diagnostics\":[],"
             + "\"warnings\":[]}";
    }

    // ── RESOLVE WITNESS ────────────────────────────────────────────────────────

    private static String resolveWitness(String req) throws Exception {
        String wsRoot     = jsonString(req, "workspace_root");
        if (wsRoot.isEmpty()) wsRoot = ".";
        String pinnedCid  = jsonString(req, "witness_cid");
        String witnessKind = jsonString(req, "witness_kind");
        String packageDir = jsonString(req, "package_dir");

        if (pinnedCid.isEmpty()) {
            throw new IllegalArgumentException("resolve_witness requires a witness_cid");
        }

        Path projectDir = Path.of(wsRoot);

        // 1. PACKAGE: try reading a pre-written .witness file
        if (!packageDir.isEmpty()) {
            Path pd = Path.of(packageDir).isAbsolute()
                    ? Path.of(packageDir) : projectDir.resolve(packageDir);
            Path wf = pd.resolve(pinnedCid.replace(":", "_") + ".witness");
            if (Files.isRegularFile(wf)) {
                byte[] bytes = Files.readAllBytes(wf);
                return resolveResult(pinnedCid, bytes, "package");
            }
        }

        // 2. RECOMPUTE: re-run the suite
        if (!witnessKind.isEmpty() && !witnessKind.equals("junit-test-witness-package")) {
            throw new IllegalArgumentException(
                "cannot recompute witness_kind=" + witnessKind
                + "; expected junit-test-witness-package");
        }

        LiftResult lr = runAndBuildBundle(projectDir);
        if (!lr.bundleCid.equals(pinnedCid)) {
            throw new IllegalArgumentException(
                "witness package did not reproduce: recomputed "
                + lr.bundleCid + ", pinned " + pinnedCid);
        }
        return resolveResult(pinnedCid, lr.bundleBytes, "recompute");
    }

    private static String resolveResult(String cid, byte[] bytes, String by) {
        return "{\"witness_cid\":" + jsl(cid)
             + ",\"body_b64\":" + jsl(Base64.getEncoder().encodeToString(bytes))
             + ",\"resolved_by\":" + jsl(by) + "}";
    }

    // ── Bundle construction ────────────────────────────────────────────────────

    record LiftResult(
        byte[]       bundleBytes,
        String       bundleCid,
        String       runtimeCid,
        List<String> codeFiles,
        List<String> testFiles,
        int          count,
        int          passed
    ) {}

    private static LiftResult runAndBuildBundle(Path projectDir) throws Exception {
        // Discover Java sources
        List<Path> srcFiles = discoverJavaSources(projectDir);
        if (srcFiles.isEmpty()) {
            throw new IllegalStateException(
                "no Java source files found under " + projectDir);
        }
        srcFiles.sort(Comparator.naturalOrder());

        // Project-relative code file paths (sorted, '/' separator for CID)
        List<String> codeFiles = srcFiles.stream()
            .map(p -> projectDir.relativize(p).toString()
                                .replace(File.separatorChar, '/'))
            .sorted()
            .collect(Collectors.toList());

        List<String> testFiles = List.of(".");
        String codeCid    = computeCodeCid(projectDir, codeFiles);
        String runtimeCid = computeRuntimeCid();

        // Compile to temp dir
        Path outDir = Files.createTempDirectory("java-witness-");
        try {
            compileJavaSources(srcFiles, outDir);

            URL[] urls = { outDir.toUri().toURL() };
            try (URLClassLoader loader = new URLClassLoader(
                    urls, Thread.currentThread().getContextClassLoader())) {

                List<TestResult> results = runTests(loader, outDir);
                if (results.isEmpty()) {
                    throw new IllegalStateException(
                        "no test methods found in " + projectDir);
                }
                results.sort(Comparator.comparing(r -> r.testId));

                ByteArrayOutputStream buf = new ByteArrayOutputStream();
                int passed = 0;
                for (TestResult tr : results) {
                    String line = witnessLine(
                        codeCid, runtimeCid, tr.testId, tr.outcome, codeFiles);
                    buf.write(line.getBytes(StandardCharsets.UTF_8));
                    buf.write('\n');
                    if ("passed".equals(tr.outcome)) passed++;
                }
                byte[] bundleBytes = buf.toByteArray();
                String bundleCid   = blake3_512Of(bundleBytes);
                return new LiftResult(bundleBytes, bundleCid, runtimeCid,
                                      codeFiles, testFiles, results.size(), passed);
            }
        } finally {
            deleteTree(outDir);
        }
    }

    // ── Java source discovery ──────────────────────────────────────────────────

    private static List<Path> discoverJavaSources(Path root) throws IOException {
        List<Path> result = new ArrayList<>();
        for (String sub : new String[]{ "src", "test", "tests" }) {
            Path dir = root.resolve(sub);
            if (!Files.isDirectory(dir)) continue;
            Files.walk(dir)
                 .filter(p -> p.toString().endsWith(".java"))
                 // Skip hidden dirs in the RELATIVE path from the subdir root only
                 .filter(p -> {
                     String rel = dir.relativize(p).toString();
                     return !rel.contains(File.separator + ".")
                         && !rel.startsWith(".");
                 })
                 .forEach(result::add);
        }
        if (result.isEmpty()) {
            // Fallback: .java files directly under root (depth 1 only)
            Files.walk(root, 1)
                 .filter(p -> p.toString().endsWith(".java"))
                 .filter(p -> !p.equals(root))
                 .forEach(result::add);
        }
        return result;
    }

    // ── Compilation ────────────────────────────────────────────────────────────

    private static void compileJavaSources(List<Path> sources, Path outDir)
            throws Exception {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException(
            "no system JavaCompiler (need JDK, not just JRE)");

        List<String> args = new ArrayList<>(List.of(
            "-d", outDir.toString(),
            "-source", "21", "-target", "21",
            "-proc:none"
        ));
        sources.stream().map(Path::toString).forEach(args::add);

        StringWriter sw = new StringWriter();
        int rc = compiler.run(null, null,
            new java.io.OutputStream() {
                public void write(int b) { sw.write(b); }
                public void write(byte[] buf, int off, int len) {
                    sw.write(new String(buf, off, len, StandardCharsets.UTF_8));
                }
            }, args.toArray(String[]::new));
        if (rc != 0) throw new IllegalStateException("javac failed:\n" + sw);
    }

    // ── Test runner ────────────────────────────────────────────────────────────

    record TestResult(String testId, String outcome) {}

    private static List<TestResult> runTests(URLClassLoader loader, Path classDir)
            throws Exception {
        List<TestResult> results = new ArrayList<>();
        List<Path> classFiles = new ArrayList<>();
        Files.walk(classDir)
             .filter(p -> p.toString().endsWith(".class"))
             .filter(p -> !p.getFileName().toString().contains("$"))
             .forEach(classFiles::add);
        classFiles.sort(Comparator.naturalOrder());

        for (Path cf : classFiles) {
            String rel = classDir.relativize(cf).toString();
            String className = rel.replace(File.separatorChar, '.').replace("/", ".");
            if (className.endsWith(".class"))
                className = className.substring(0, className.length() - 6);
            try {
                Class<?> cls = loader.loadClass(className);
                if (!isTestClass(cls)) continue;
                Object inst;
                try { inst = cls.getDeclaredConstructor().newInstance(); }
                catch (Exception e) { continue; }

                for (Method m : cls.getMethods()) {
                    if (!isTestMethod(m)) continue;
                    String testId = className + "::" + m.getName();
                    String outcome;
                    try {
                        m.invoke(inst);
                        outcome = "passed";
                    } catch (InvocationTargetException ite) {
                        outcome = "failed";
                    } catch (Exception ex) {
                        outcome = "failed";
                    }
                    results.add(new TestResult(testId, outcome));
                }
            } catch (Exception ignored) {}
        }
        return results;
    }

    private static boolean isTestClass(Class<?> cls) {
        if (cls.isInterface() || cls.isAnnotation() || cls.isEnum()) return false;
        if (Modifier.isAbstract(cls.getModifiers())) return false;
        try { cls.getDeclaredConstructor(); } catch (NoSuchMethodException e) { return false; }
        for (Method m : cls.getMethods()) if (isTestMethod(m)) return true;
        return false;
    }

    private static boolean isTestMethod(Method m) {
        if (!Modifier.isPublic(m.getModifiers())) return false;
        if (m.getParameterCount() != 0) return false;
        if (m.getDeclaringClass() == Object.class) return false;
        for (java.lang.annotation.Annotation ann : m.getAnnotations()) {
            String n = ann.annotationType().getName();
            if (n.equals("org.junit.jupiter.api.Test")
             || n.equals("org.junit.Test")
             || n.endsWith(".Test")) return true;
        }
        return m.getName().startsWith("test");
    }

    // ── CID helpers ───────────────────────────────────────────────────────────

    /**
     * code_cid: blake3_512(join_nul(rel + "\0" + content)) over sorted files.
     * Mirrors rust code_cid: parts separated by \0.
     */
    private static String computeCodeCid(Path root, List<String> files)
            throws IOException {
        List<String> sorted = new ArrayList<>(files);
        Collections.sort(sorted);
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        boolean first = true;
        for (String rel : sorted) {
            byte[] content = Files.readAllBytes(root.resolve(rel));
            if (!first) buf.write(0);
            first = false;
            buf.write(rel.getBytes(StandardCharsets.UTF_8));
            buf.write(0);
            buf.write(content);
        }
        return blake3_512Of(buf.toByteArray());
    }

    /**
     * runtime_cid: blake3_512("java=<version>").
     */
    private static String computeRuntimeCid() {
        String desc = "java=" + System.getProperty("java.version", "unknown");
        return blake3_512Of(desc.getBytes(StandardCharsets.UTF_8));
    }

    // ── Witness line (JCS) ─────────────────────────────────────────────────────

    /**
     * Build one JCS line for a test.
     * Keys sorted alphabetically: codeCid, codeFiles, kind, outcome, runtimeCid, test.
     * codeFiles stored as comma-joined sorted list (mirrors rust codeFiles join).
     */
    private static String witnessLine(String codeCid, String runtimeCid,
                                       String testId, String outcome,
                                       List<String> codeFiles) {
        List<String> sorted = new ArrayList<>(codeFiles);
        Collections.sort(sorted);
        return "{\"codeCid\":" + jsl(codeCid)
             + ",\"codeFiles\":" + jsl(String.join(",", sorted))
             + ",\"kind\":\"junit-test-witness\""
             + ",\"outcome\":" + jsl(outcome)
             + ",\"runtimeCid\":" + jsl(runtimeCid)
             + ",\"test\":" + jsl(testId)
             + "}";
    }

    // ── IR construction ────────────────────────────────────────────────────────

    /**
     * proofData: sorted-key compact JSON embedded as string in the certificate.
     * Keys: codeFiles, count, kind, packageCid, passed, testFiles.
     */
    private static String buildProofData(String bundleCid, List<String> testFiles,
                                          List<String> codeFiles, int count, int passed) {
        List<String> tf = new ArrayList<>(testFiles); Collections.sort(tf);
        List<String> cf = new ArrayList<>(codeFiles); Collections.sort(cf);
        return "{\"codeFiles\":" + jsonArray(cf)
             + ",\"count\":" + count
             + ",\"kind\":\"witness-package\""
             + ",\"packageCid\":" + jsl(bundleCid)
             + ",\"passed\":" + passed
             + ",\"testFiles\":" + jsonArray(tf) + "}";
    }

    /**
     * Contract IR member: tool="junit" → verifier maps to "junit-test-witness-package".
     */
    private static String buildContractIr(String bundleCid, String runtimeCid,
                                           String proofData) {
        String cert = "{\"formulaHash\":" + jsl(bundleCid)
                    + ",\"proofData\":" + jsl(proofData)
                    + ",\"tool\":\"junit\""
                    + ",\"version\":" + jsl(runtimeCid) + "}";
        String evidence = "{\"certificate\":" + cert + ",\"proofType\":\"custom\"}";
        return "{\"kind\":\"contract\""
             + ",\"name\":" + jsl("witness-package:" + bundleCid)
             + ",\"inv\":{\"kind\":\"atomic\",\"name\":\"witnessed\",\"args\":[]}"
             + ",\"pre\":null,\"post\":null"
             + ",\"out_binding\":\"out\""
             + ",\"evidence\":" + evidence
             + ",\"panic_loci\":[]}";
    }

    /**
     * WitnessPackageMemento — carried alongside the contract in the .proof.
     */
    private static String buildMemento(String bundleCid, List<String> testFiles,
                                        List<String> codeFiles, int count, int passed)
            throws Exception {
        List<String> tf = new ArrayList<>(testFiles); Collections.sort(tf);
        List<String> cf = new ArrayList<>(codeFiles); Collections.sort(cf);
        byte[] seed   = resolveSignerSeed();
        String signer = "ed25519:" + Base64.getEncoder().encodeToString(ed25519Pubkey(seed));
        // The mark is over the bundle CID bytes -- exactly what the rust verifier
        // re-checks (ed25519_verify_string over witness_cid.as_bytes()).
        String sig    = "ed25519:" + Base64.getEncoder().encodeToString(
            ed25519Sign(seed, bundleCid.getBytes(StandardCharsets.UTF_8)));
        return "{\"kind\":\"witness-memento\""
             + ",\"witness_kind\":\"junit-test-witness-package\""
             + ",\"witness_cid\":" + jsl(bundleCid)
             + ",\"signer\":" + jsl(signer)
             + ",\"signature\":" + jsl(sig)
             + ",\"count\":" + count
             + ",\"passed\":" + passed
             + ",\"test_files\":" + jsonArray(tf)
             + ",\"code_files\":" + jsonArray(cf) + "}";
    }

    // ── File utils ─────────────────────────────────────────────────────────────

    private static void deleteTree(Path dir) {
        try {
            Files.walk(dir)
                 .sorted(Comparator.reverseOrder())
                 .map(Path::toFile)
                 .forEach(File::delete);
        } catch (IOException ignored) {}
    }

    // ══════════════════════════════════════════════════════════════════════════
    // BLAKE3-512 XOF — pure Java, JDK-only.
    //
    // Implements the BLAKE3 specification exactly, producing 64 bytes of XOF
    // output (== BLAKE3-512). Verified against the reference Python blake3
    // library for: b"", b"hello", b"BLAKE3 test", b"x"*100, b"y"*2048.
    //
    // Protocol: "blake3-512:" + lowercase-hex(64-byte digest).
    // ══════════════════════════════════════════════════════════════════════════

    // BLAKE3 IV = SHA-256 IV (first 8 words)
    private static final int[] B3_IV = {
        0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
        0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19
    };

    // BLAKE3 message schedule permutation (one fixed permutation applied 7 times)
    private static final int[] MSG_PERM = {
        2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8
    };

    // Domain separation flags
    private static final int B3_CHUNK_START = 1;
    private static final int B3_CHUNK_END   = 2;
    private static final int B3_PARENT      = 4;
    private static final int B3_ROOT        = 8;

    private static final int B3_CHUNK_SIZE  = 1024;
    private static final int B3_BLOCK_SIZE  = 64;

    /** BLAKE3 G mixing function. Mutates state in-place. */
    private static void b3G(int[] s, int a, int b, int c, int d, int mx, int my) {
        s[a] = s[a] + s[b] + mx;
        s[d] = Integer.rotateRight(s[d] ^ s[a], 16);
        s[c] = s[c] + s[d];
        s[b] = Integer.rotateRight(s[b] ^ s[c], 12);
        s[a] = s[a] + s[b] + my;
        s[d] = Integer.rotateRight(s[d] ^ s[a],  8);
        s[c] = s[c] + s[d];
        s[b] = Integer.rotateRight(s[b] ^ s[c],  7);
    }

    /**
     * BLAKE3 compress: takes 8-word CV, 16-word block, 64-bit counter,
     * block-len-in-bytes, flags; returns 16-word state.
     * First 8 words = new CV; all 16 = XOF material.
     */
    private static int[] b3Compress(int[] cv, int[] block,
                                     long counter, int blen, int flags) {
        int[] s = {
            cv[0],    cv[1],    cv[2],    cv[3],
            cv[4],    cv[5],    cv[6],    cv[7],
            B3_IV[0], B3_IV[1], B3_IV[2], B3_IV[3],
            (int) counter, (int)(counter >>> 32), blen, flags
        };
        int[] m = block.clone();
        for (int round = 0; round < 7; round++) {
            // column step
            b3G(s, 0, 4,  8, 12, m[0],  m[1]);
            b3G(s, 1, 5,  9, 13, m[2],  m[3]);
            b3G(s, 2, 6, 10, 14, m[4],  m[5]);
            b3G(s, 3, 7, 11, 15, m[6],  m[7]);
            // diagonal step
            b3G(s, 0, 5, 10, 15, m[8],  m[9]);
            b3G(s, 1, 6, 11, 12, m[10], m[11]);
            b3G(s, 2, 7,  8, 13, m[12], m[13]);
            b3G(s, 3, 4,  9, 14, m[14], m[15]);
            // permute message words for next round
            int[] nm = new int[16];
            for (int i = 0; i < 16; i++) nm[i] = m[MSG_PERM[i]];
            m = nm;
        }
        // finalize: XOR both halves
        for (int i = 0; i < 8; i++) {
            s[i]     ^= s[i + 8];
            s[i + 8] ^= cv[i];
        }
        return s;
    }

    /** Read up to 16 LE 32-bit words from data[offset..offset+len]. Zero-pad. */
    private static int[] b3ReadBlock(byte[] data, int offset, int len) {
        int[] block = new int[16];
        int end = Math.min(offset + len, data.length);
        for (int i = offset; i < end; i++) {
            int wi = (i - offset) >> 2;
            int bi = (i - offset) & 3;
            block[wi] |= (data[i] & 0xFF) << (bi << 3);
        }
        return block;
    }

    /**
     * Process one full chunk (up to 1024 bytes) and return its 8-word CV.
     * Does NOT set ROOT: chunk CVs are leaves or interior nodes.
     */
    private static int[] b3ProcessChunk(byte[] data, int offset, int chunkLen,
                                         long chunkCounter) {
        int[] cv        = B3_IV.clone();
        int   pos       = offset;
        int   remaining = chunkLen;
        int   numBlocks = Math.max(1, (chunkLen + B3_BLOCK_SIZE - 1) / B3_BLOCK_SIZE);

        for (int bi = 0; bi < numBlocks; bi++) {
            int blen  = Math.min(remaining, B3_BLOCK_SIZE);
            int flags = 0;
            if (bi == 0)             flags |= B3_CHUNK_START;
            if (bi == numBlocks - 1) flags |= B3_CHUNK_END;

            int[] block = b3ReadBlock(data, pos, blen);
            int[] out   = b3Compress(cv, block, chunkCounter, blen, flags);
            cv        = Arrays.copyOf(out, 8);
            pos      += blen;
            remaining -= blen;
        }
        return cv;
    }

    /**
     * Process the last block of a chunk with ROOT flag and return all 16 output
     * words (for XOF).  Used when the input fits in a single chunk.
     */
    private static int[] b3SingleChunkRoot(byte[] data, int length) {
        int[] cv        = B3_IV.clone();
        int   numBlocks = Math.max(1, (length + B3_BLOCK_SIZE - 1) / B3_BLOCK_SIZE);
        int   pos       = 0;
        int   remaining = length;

        for (int bi = 0; bi < numBlocks; bi++) {
            int blen   = Math.min(remaining, B3_BLOCK_SIZE);
            boolean last = (bi == numBlocks - 1);
            int flags  = 0;
            if (bi == 0) flags |= B3_CHUNK_START;
            if (last)    flags |= B3_CHUNK_END;
            if (last)    flags |= B3_ROOT;

            int[] block = b3ReadBlock(data, pos, blen);
            int[] out   = b3Compress(cv, block, 0L, blen, flags);
            if (last) return out;   // 16 words = 64 bytes of XOF
            cv        = Arrays.copyOf(out, 8);
            pos      += blen;
            remaining -= blen;
        }
        throw new AssertionError("unreachable");
    }

    /**
     * BLAKE3 hash with 64-byte XOF output.
     * Handles single-chunk and multi-chunk inputs correctly.
     */
    static byte[] blake3Xof64(byte[] input) {
        int[] xofWords;

        if (input.length <= B3_CHUNK_SIZE) {
            // Single chunk: last compress gets ROOT flag
            xofWords = b3SingleChunkRoot(input, input.length);
        } else {
            // Multi-chunk: build Merkle tree, final parent merge gets ROOT
            int numChunks = (input.length + B3_CHUNK_SIZE - 1) / B3_CHUNK_SIZE;
            int[][] level = new int[numChunks][];
            for (int i = 0; i < numChunks; i++) {
                int off  = i * B3_CHUNK_SIZE;
                int clen = Math.min(B3_CHUNK_SIZE, input.length - off);
                level[i] = b3ProcessChunk(input, off, clen, i);
            }
            // Merge bottom-up; final merge gets ROOT
            while (level.length > 1) {
                int newLen  = (level.length + 1) / 2;
                boolean isLastLevel = (newLen == 1);
                int[][] next = new int[newLen][];
                for (int i = 0; i < newLen; i++) {
                    int li = i * 2, ri = li + 1;
                    if (ri >= level.length) {
                        next[i] = level[li]; // odd: promote unchanged
                        continue;
                    }
                    int[] block = new int[16];
                    System.arraycopy(level[li], 0, block, 0, 8);
                    System.arraycopy(level[ri], 0, block, 8, 8);
                    int flags = B3_PARENT | (isLastLevel ? B3_ROOT : 0);
                    int[] out = b3Compress(B3_IV.clone(), block, 0L, 64, flags);
                    next[i] = isLastLevel ? out : Arrays.copyOf(out, 8);
                }
                level = next;
            }
            xofWords = level[0]; // 16 words when ROOT was set on last merge
        }

        // Convert 16 LE words → 64 bytes
        byte[] result = new byte[64];
        for (int i = 0; i < 16; i++) {
            result[i*4]   = (byte)  xofWords[i];
            result[i*4+1] = (byte) (xofWords[i] >>> 8);
            result[i*4+2] = (byte) (xofWords[i] >>> 16);
            result[i*4+3] = (byte) (xofWords[i] >>> 24);
        }
        return result;
    }

    /** Hash bytes → "blake3-512:" + lowercase hex (128 chars). */
    static String blake3_512Of(byte[] bytes) {
        byte[] digest = blake3Xof64(bytes);
        StringBuilder sb = new StringBuilder("blake3-512:");
        for (byte b : digest) sb.append(String.format("%02x", b & 0xFF));
        return sb.toString();
    }

    // ══════════════════════════════════════════════════════════════════════════
    // Ed25519 witness signing — JDK-only.
    //
    // The witness memento carries OUR signed mark over the bundle CID bytes:
    // signature = ed25519(seed, witness_cid.bytes), signer = ed25519 pubkey.
    // The rust verifier re-checks exactly this (`ed25519_verify_string` over
    // `witness_cid.as_bytes()`), so the strings must be byte-identical in form:
    //   "ed25519:" + base64-std(32-byte pubkey)  /  + base64-std(64-byte sig).
    //
    // SEED RESOLUTION mirrors the rust kit: SUGAR_WITNESS_SIGNER_SEED (64 hex
    // chars) wins; else the well-known DEV seed = 32 bytes of 0x77 (an INTEGRITY
    // TAG only -- it proves the body was not altered, not WHO signed it).
    //
    // The JDK signs from a raw seed (Signature "Ed25519" + EdECPrivateKeySpec),
    // but exposes no raw pubkey from a private key, so the public key is derived
    // here via the RFC 8032 base-point scalar mult (SHA-512(seed) -> clamp ->
    // [a]B -> compress). Verified to reproduce the rust dev-seed pubkey exactly.
    // ══════════════════════════════════════════════════════════════════════════

    private static final String SIGNER_SEED_ENV = "SUGAR_WITNESS_SIGNER_SEED";

    private static byte[] resolveSignerSeed() {
        String env = System.getenv(SIGNER_SEED_ENV);
        if (env != null) {
            env = env.trim();
            if (!env.isEmpty()) {
                if (env.length() != 64) {
                    throw new IllegalArgumentException(
                        SIGNER_SEED_ENV + " must be 64 hex chars (32 bytes); got " + env.length());
                }
                byte[] out = new byte[32];
                for (int i = 0; i < 32; i++) {
                    out[i] = (byte) Integer.parseInt(env.substring(i*2, i*2+2), 16);
                }
                return out;
            }
        }
        byte[] dev = new byte[32];
        Arrays.fill(dev, (byte) 0x77);
        return dev;
    }

    private static byte[] ed25519Sign(byte[] seed, byte[] message) throws Exception {
        java.security.spec.NamedParameterSpec ns =
            new java.security.spec.NamedParameterSpec("Ed25519");
        java.security.KeyFactory kf = java.security.KeyFactory.getInstance("Ed25519");
        java.security.spec.EdECPrivateKeySpec spec =
            new java.security.spec.EdECPrivateKeySpec(ns, seed);
        java.security.PrivateKey priv = kf.generatePrivate(spec);
        java.security.Signature sig = java.security.Signature.getInstance("Ed25519");
        sig.initSign(priv);
        sig.update(message);
        return sig.sign();
    }

    // ── RFC 8032 Ed25519 public-key derivation (Edwards curve, pure Java) ───────

    private static final BigInteger ED_P =
        BigInteger.TWO.pow(255).subtract(BigInteger.valueOf(19));
    private static final BigInteger ED_D = BigInteger.valueOf(-121665)
        .multiply(BigInteger.valueOf(121666).modInverse(ED_P)).mod(ED_P);
    private static final BigInteger ED_SQRT_M1 = BigInteger.TWO.modPow(
        ED_P.subtract(BigInteger.ONE).divide(BigInteger.valueOf(4)), ED_P);

    private static BigInteger edInv(BigInteger x) {
        return x.modPow(ED_P.subtract(BigInteger.TWO), ED_P);
    }

    private static BigInteger edRecoverX(BigInteger y, boolean xBit) {
        BigInteger x2 = y.multiply(y).subtract(BigInteger.ONE)
            .multiply(edInv(ED_D.multiply(y).multiply(y).add(BigInteger.ONE))).mod(ED_P);
        if (x2.signum() == 0) return BigInteger.ZERO;
        BigInteger x = x2.modPow(
            ED_P.add(BigInteger.valueOf(3)).divide(BigInteger.valueOf(8)), ED_P);
        if (x.multiply(x).subtract(x2).mod(ED_P).signum() != 0)
            x = x.multiply(ED_SQRT_M1).mod(ED_P);
        if (x.testBit(0) != xBit) x = ED_P.subtract(x);
        return x;
    }

    /** Extended-coordinate point add on the Edwards curve. p,q = {X,Y,Z,T}. */
    private static BigInteger[] edAdd(BigInteger[] p, BigInteger[] q) {
        BigInteger A = p[0].subtract(p[1]).multiply(q[0].subtract(q[1])).mod(ED_P);
        BigInteger B = p[0].add(p[1]).multiply(q[0].add(q[1])).mod(ED_P);
        BigInteger C = BigInteger.TWO.multiply(p[3]).multiply(q[3]).multiply(ED_D).mod(ED_P);
        BigInteger Dd = BigInteger.TWO.multiply(p[2]).multiply(q[2]).mod(ED_P);
        BigInteger E = B.subtract(A), F = Dd.subtract(C), G = Dd.add(C), H = B.add(A);
        return new BigInteger[]{
            E.multiply(F).mod(ED_P), G.multiply(H).mod(ED_P),
            F.multiply(G).mod(ED_P), E.multiply(H).mod(ED_P)};
    }

    private static BigInteger[] edMul(BigInteger s, BigInteger[] p) {
        BigInteger[] q = {BigInteger.ZERO, BigInteger.ONE, BigInteger.ONE, BigInteger.ZERO};
        while (s.signum() > 0) {
            if (s.testBit(0)) q = edAdd(q, p);
            p = edAdd(p, p);
            s = s.shiftRight(1);
        }
        return q;
    }

    private static byte[] edCompress(BigInteger[] p) {
        BigInteger zinv = edInv(p[2]);
        BigInteger x = p[0].multiply(zinv).mod(ED_P);
        BigInteger y = p[1].multiply(zinv).mod(ED_P);
        BigInteger enc = y.or(x.testBit(0) ? BigInteger.TWO.pow(255) : BigInteger.ZERO);
        byte[] out = new byte[32];
        byte[] be = enc.toByteArray(); // big-endian, possibly with a leading 0
        for (int i = 0; i < be.length; i++) {
            int idx = be.length - 1 - i;   // little-endian slot
            if (idx < 32) out[idx] = be[i];
        }
        return out;
    }

    private static byte[] ed25519Pubkey(byte[] seed) throws Exception {
        java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-512");
        byte[] h = md.digest(seed);
        byte[] a = Arrays.copyOfRange(h, 0, 32);
        a[0]  &= (byte) 0xF8;
        a[31] &= (byte) 0x7F;
        a[31] |= (byte) 0x40;
        BigInteger s = BigInteger.ZERO;             // little-endian scalar
        for (int i = 31; i >= 0; i--) s = s.shiftLeft(8).or(BigInteger.valueOf(a[i] & 0xFF));
        BigInteger by = BigInteger.valueOf(4)
            .multiply(BigInteger.valueOf(5).modInverse(ED_P)).mod(ED_P);
        BigInteger bx = edRecoverX(by, false);
        BigInteger[] base = {bx, by, BigInteger.ONE, bx.multiply(by).mod(ED_P)};
        return edCompress(edMul(s, base));
    }
}
