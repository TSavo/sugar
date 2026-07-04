// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Java-native Panama FFM call-edge lifter for the Sugar/ProvekIt substrate.
//
// THE LAW: every fact about Java source comes from a com.sun.source.tree.*
// node. No regex, indexOf, split, or any string-scanning of Java source code
// is used here. JSON-RPC wire protocol codec uses indexOf/split on JSON bytes
// only — not on Java source.
//
// WHAT THIS LIFTER DOES (P5b — bridge role):
//   For each *.java file:
//   1. Parse via JavacTask + Trees.instance(task).getSourcePositions() for
//      accurate line/column on callsite nodes.
//   2. Walk VariableTree (static fields) — detect Panama downcall handles:
//      field initialized by Linker.downcallHandle(..., lookup.find("sym").orElseThrow(), ...)
//      → records fieldName → nativeSymbolName.
//   3. Walk MethodTree (non-@Test methods) — detect bridge wrapper methods:
//      body contains FIELD.invokeExact(...) or FIELD.invoke(...) where FIELD is
//      a known downcall-handle field.
//      → records wrapperMethodName → fieldName.
//   4. Walk @Test MethodTree — find assertEquals(literal, wrapper(arg)) callsites:
//      → emits a call-edge from the Java #euf# contract to the native contract.
//
// SURFACE: "java-panama-ffm" — matches the deleted PanamaFfmLiftRpc.java.
// OUTPUT SHAPE: byte-identical to deleted lifter's callEdgeJson().

import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public final class JavaPanamaFfmRpc {

    private static final String SURFACE = "java-panama-ffm";
    private static final String VERSION = "0.1.0";

    // ── Entry point: JSON-RPC 2.0 over stdin/stdout ────────────────────────────

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(
                new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) continue;
            String id = extractId(line);
            String method = jsonString(line, "method").orElse("");
            String response;
            try {
                response = switch (method) {
                    case "initialize"                      -> ok(id, initializeResult());
                    case "sugar.plugin.kit_declaration"   -> ok(id, kitDeclarationResult());
                    case "sugar.plugin.resolve_dependency_proofs" -> ok(id,
                            JavaDependencyProofResolver.resolveDependencyProofs(line));
                    case "lift"                            -> ok(id, lift(line));
                    case "shutdown", "sugar.plugin.shutdown" -> ok(id, "null");
                    default -> error(id, -32601, "unknown method: " + method);
                };
            } catch (Exception e) {
                response = error(id, -32603, e.getMessage() == null ? e.toString() : e.getMessage());
            }
            System.out.println(response);
            System.out.flush();
            if ("shutdown".equals(method) || "sugar.plugin.shutdown".equals(method)) break;
        }
    }

    // ── Protocol responses ─────────────────────────────────────────────────────

    private static String initializeResult() {
        return "{"
            + "\"name\":\"sugar-lift-java-panama-ffm\","
            + "\"version\":\"" + VERSION + "\","
            + "\"protocol_version\":\"pep/1.7.0\","
            + "\"capabilities\":{"
            + "\"authoring_surfaces\":[\"" + SURFACE + "\"],"
            + "\"ir_version\":\"v1.1.0\","
            + "\"emits_signed_mementos\":false"
            + "}"
            + "}";
    }

    private static String kitDeclarationResult() {
        return "{"
            + "\"kit\":{\"id\":\"" + SURFACE + "\",\"language\":\"java\",\"version\":\"" + VERSION + "\"},"
            + "\"rpc\":{\"methods\":["
            + "{\"name\":\"initialize\",\"required\":true},"
            + "{\"name\":\"sugar.plugin.kit_declaration\",\"required\":true},"
            + "{\"name\":\"sugar.plugin.resolve_dependency_proofs\",\"required\":false},"
            + "{\"name\":\"lift\",\"required\":true},"
            + "{\"name\":\"shutdown\",\"required\":false}"
            + "]},"
            + "\"proofResolution\":{\"strategy\":\"maven\","
            + "\"rpcMethod\":\"sugar.plugin.resolve_dependency_proofs\"},"
            + "\"effectKinds\":[],\"effectLeaves\":[],\"guardPredicates\":[],"
            + "\"controlCarriers\":[],\"residueCategories\":[]"
            + "}";
    }

    // ── lift: parse every *.java via JavacTask, walk AST for Panama bridges ────

    private static String lift(String requestJson) throws IOException {
        String workspaceRoot = jsonString(requestJson, "workspace_root").orElse(".");
        Path root = Path.of(workspaceRoot);
        List<String> sourcePaths = jsonStringArray(requestJson, "source_paths");
        if (sourcePaths.isEmpty()) sourcePaths = List.of(".");
        List<Binding> bindings = parseContractBindings(requestJson);

        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            return irDoc(List.of(),
                List.of(diagnostic("", "no-compiler", "no JavaCompiler available")));
        }

        List<String> javaFiles = enumerateJavaFiles(root, sourcePaths);
        List<String> edges = new ArrayList<>();
        List<String> diagnostics = new ArrayList<>();
        Set<String> seen = new HashSet<>();

        for (String rel : javaFiles) {
            Path abs = root.resolve(rel);
            liftFile(compiler, abs, rel, root, bindings, edges, diagnostics, seen);
        }

        edges.sort(Comparator.naturalOrder());

        // Sidecar for the verifier's call_edge_loader
        Path sidecar = root.resolve("java-panama-ffm.call-edges.json");
        Files.writeString(sidecar,
            "{\"edges\":[" + String.join(",", edges) + "]}\n",
            StandardCharsets.UTF_8);

        return irDoc(edges, diagnostics);
    }

    private static String irDoc(List<String> edges, List<String> diags) {
        String e = String.join(",", edges);
        String d = String.join(",", diags);
        return "{\"kind\":\"ir-document\","
            + "\"ir\":[" + e + "],"
            + "\"callEdges\":[" + e + "],"
            + "\"diagnostics\":[" + d + "],"
            + "\"refusals\":[]}";
    }

    // ── Per-file lift ──────────────────────────────────────────────────────────

    private static void liftFile(
            JavaCompiler compiler,
            Path abs,
            String rel,
            Path root,
            List<Binding> bindings,
            List<String> edges,
            List<String> diagnostics,
            Set<String> seen) throws IOException {

        String source = Files.readString(abs, StandardCharsets.UTF_8);
        JavaFileObject fo = new StringJavaFileObject(abs.toString(), source);
        StandardJavaFileManager fm = compiler.getStandardFileManager(null, null, StandardCharsets.UTF_8);

        // No --release: com.sun.source.util.Trees needs no --release
        JavacTask task = (JavacTask) compiler.getTask(null, fm, null, List.of(), null, List.of(fo));

        Iterable<? extends CompilationUnitTree> units;
        try {
            units = task.parse();
        } catch (IOException e) {
            diagnostics.add(diagnostic(rel, "parse-io-error", e.getMessage()));
            fm.close();
            return;
        }

        // SourcePositions — the official API, avoids any internal cast
        Trees trees = Trees.instance(task);
        SourcePositions sp = trees.getSourcePositions();

        for (CompilationUnitTree unit : units) {
            LineMap lm = unit.getLineMap();
            FileAnalysis fa = analyzeUnit(unit);

            if (fa.fieldToSymbol.isEmpty()) continue; // no Panama handles here

            // Now walk @Test methods for callsites using source positions
            for (ClassTree cls : fa.classes) {
                for (MethodTree mt : fa.testMethods.getOrDefault(cls, List.of())) {
                    String testName = mt.getName().toString();
                    BlockTree body = mt.getBody();
                    if (body == null) continue;

                    for (StatementTree stmt : body.getStatements()) {
                        if (!(stmt instanceof ExpressionStatementTree est)) continue;
                        ExpressionTree expr = est.getExpression();
                        if (!(expr instanceof MethodInvocationTree assertMit)) continue;
                        if (!simpleName(assertMit).equals("assertEquals")) continue;

                        List<? extends ExpressionTree> aArgs = assertMit.getArguments();
                        if (aArgs.size() < 2) continue;

                        // arg[0]: expected literal (int/long/string)
                        if (!(aArgs.get(0) instanceof LiteralTree)) continue;
                        LiteralTree expectedLit = (LiteralTree) aArgs.get(0);

                        // arg[1]: wrapper call, possibly wrapped in casts/toIntExact
                        ExpressionTree callExpr = peelToWrapperCall(aArgs.get(1), fa.wrapperToField);
                        if (!(callExpr instanceof MethodInvocationTree wrapperMit)) continue;
                        String wrapperName = simpleName(wrapperMit);
                        if (!fa.wrapperToField.containsKey(wrapperName)) continue;

                        // arg of wrapper call: must be a literal
                        List<? extends ExpressionTree> wArgs = wrapperMit.getArguments();
                        if (wArgs.isEmpty()) continue;
                        if (!(wArgs.get(0) instanceof LiteralTree argLit)) continue;

                        String argValue = String.valueOf(argLit.getValue());

                        // Source position of the wrapper MethodInvocationTree
                        long pos = sp.getStartPosition(unit, wrapperMit);
                        int line = 0, column = 0;
                        if (pos >= 0 && lm != null) {
                            line   = (int) lm.getLineNumber(pos);
                            column = (int) lm.getColumnNumber(pos);
                        }

                        // Build the #euf# name and resolve bindings.
                        // The #euf# symbol IS the cross-language identity (no hub). A Rust
                        // contract row name may be location-qualified for per-occurrence
                        // disambiguation (`file::module::fn::SYMBOL#euf#...`), while the Java
                        // consumer's own row is the bare SYMBOL. Match on the EUF symbol
                        // identity: the bare name, or that name as the `::`-delimited tail of
                        // a qualified name. The location prefix is sugar and dissolves.
                        String eufName = eufAssertionName(wrapperName, argValue);

                        Optional<Binding> src = bindings.stream()
                            .filter(b -> (b.name.equals(eufName) || b.name.endsWith("::" + eufName))
                                && b.targetProofCid == null)
                            .findFirst();
                        Optional<Binding> tgt = bindings.stream()
                            .filter(b -> (b.name.equals(eufName) || b.name.endsWith("::" + eufName))
                                && b.targetProofCid != null)
                            .findFirst();

                        String relPath = root.relativize(abs).toString().replace('\\', '/');

                        if (src.isEmpty()) {
                            diagnostics.add(diagnostic(relPath, "missing-source-binding", eufName));
                            continue;
                        }
                        if (tgt.isEmpty()) {
                            diagnostics.add(diagnostic(relPath, "missing-target-binding", eufName));
                            continue;
                        }

                        String targetSymbol = "rust-kit:" + eufName;
                        String edgeJson = callEdgeJson(
                            src.get().cid,
                            tgt.get().cid,
                            targetSymbol,
                            relPath,
                            line, column,
                            testName);

                        String key = src.get().cid + "\n" + targetSymbol + "\n" + relPath
                            + "\n" + line + "\n" + column;
                        if (seen.add(key)) edges.add(edgeJson);
                    }
                }
            }
        }
        fm.close();
    }

    // ── FileAnalysis: structural walk of a CompilationUnit ────────────────────

    /** Results of walking one CompilationUnitTree for Panama bridge structure. */
    private record FileAnalysis(
        /** fieldName → nativeSymbolName: from downcallHandle(.find("sym")) fields */
        Map<String, String> fieldToSymbol,
        /** wrapperMethodName → fieldName: from methods that .invokeExact() a handle field */
        Map<String, String> wrapperToField,
        /** All ClassTree nodes found in this unit */
        List<ClassTree> classes,
        /** Per-class: list of @Test MethodTree members */
        Map<ClassTree, List<MethodTree>> testMethods
    ) {}

    private static FileAnalysis analyzeUnit(CompilationUnitTree unit) {
        Map<String, String> fieldToSymbol  = new LinkedHashMap<>();
        Map<String, String> wrapperToField = new LinkedHashMap<>();
        List<ClassTree>     classes        = new ArrayList<>();
        Map<ClassTree, List<MethodTree>> testMethods = new LinkedHashMap<>();

        // Walk all class declarations (top-level + nested)
        collectClasses(unit.getTypeDecls(), classes);

        // Pass 1: collect handle fields from ALL classes
        for (ClassTree cls : classes) {
            for (Tree member : cls.getMembers()) {
                if (member instanceof VariableTree vt) {
                    detectHandleField(vt, fieldToSymbol);
                }
            }
        }

        // Pass 2: collect wrapper methods (needs fieldToSymbol complete)
        for (ClassTree cls : classes) {
            for (Tree member : cls.getMembers()) {
                if (member instanceof MethodTree mt) {
                    detectWrapperMethod(mt, fieldToSymbol, wrapperToField);
                }
            }
        }

        // Pass 3: collect @Test methods (they are the callsite sources)
        for (ClassTree cls : classes) {
            List<MethodTree> tests = new ArrayList<>();
            for (Tree member : cls.getMembers()) {
                if (member instanceof MethodTree mt && hasTestAnnotation(mt)) {
                    tests.add(mt);
                }
            }
            if (!tests.isEmpty()) testMethods.put(cls, tests);
        }

        return new FileAnalysis(fieldToSymbol, wrapperToField, classes, testMethods);
    }

    private static void collectClasses(List<? extends Tree> decls, List<ClassTree> out) {
        for (Tree d : decls) {
            if (d instanceof ClassTree ct) {
                out.add(ct);
                collectClasses(ct.getMembers(), out);
            }
        }
    }

    // ── Handle-field detection (AST, no regex) ────────────────────────────────

    /**
     * Detect: static final MethodHandle FIELD = LINKER.downcallHandle(
     *     LOOKUP.find("symbol_name").orElseThrow(),
     *     FunctionDescriptor.of(...));
     *
     * AST path:
     *   VariableTree.initializer
     *     MethodInvocationTree  (downcallHandle)
     *       methodSelect: MemberSelectTree { identifier="downcallHandle" }
     *       arguments[0]: the MemorySegment — we unwrap orElseThrow/orElse chain
     *         to find the .find("sym") MethodInvocationTree
     *           arguments[0]: LiteralTree(String) = native symbol name
     */
    private static void detectHandleField(VariableTree vt, Map<String, String> fieldToSymbol) {
        ExpressionTree init = vt.getInitializer();
        if (init == null) return;
        init = unwrapCast(init);
        if (!(init instanceof MethodInvocationTree dcMit)) return;
        if (!simpleName(dcMit).equals("downcallHandle")) return;

        List<? extends ExpressionTree> dcArgs = dcMit.getArguments();
        if (dcArgs.isEmpty()) return;

        // Peel the Optional chain (orElseThrow, orElse, get) to reach .find(...)
        ExpressionTree symbolArg = peelOptionalChain(dcArgs.get(0));
        if (!(symbolArg instanceof MethodInvocationTree findMit)) return;
        if (!simpleName(findMit).equals("find")) return;

        List<? extends ExpressionTree> findArgs = findMit.getArguments();
        if (findArgs.isEmpty()) return;
        if (!(findArgs.get(0) instanceof LiteralTree symLit)) return;
        if (!(symLit.getValue() instanceof String nativeSym)) return;

        fieldToSymbol.put(vt.getName().toString(), nativeSym);
    }

    /**
     * Peel orElseThrow() / orElse(null) / get() / orElseGet(...) chain from an
     * expression to reveal the inner .find(...) call.
     * These are all single-argument or no-argument MethodInvocationTrees whose
     * receiver is another MethodInvocationTree. We peel up to 4 layers.
     */
    private static ExpressionTree peelOptionalChain(ExpressionTree expr) {
        for (int d = 0; d < 4; d++) {
            expr = unwrapCast(expr);
            if (!(expr instanceof MethodInvocationTree mit)) return expr;
            String name = simpleName(mit);
            if (name.equals("find")) return mit; // found it
            // peel: go to the receiver
            ExpressionTree sel = mit.getMethodSelect();
            if (!(sel instanceof MemberSelectTree mst)) return expr;
            expr = mst.getExpression();
        }
        return expr;
    }

    // ── Wrapper-method detection (AST, no regex) ──────────────────────────────

    /**
     * Detect: [static] returnType wrapperMethod(...) throws Throwable {
     *     return (cast) HANDLE_FIELD.invokeExact(args...);
     * }
     *
     * We search the method body for a MethodInvocationTree whose name is
     * "invokeExact" or "invoke" and whose receiver (MemberSelectTree.expression)
     * is an IdentifierTree naming a known handle field.
     */
    private static void detectWrapperMethod(
            MethodTree mt,
            Map<String, String> fieldToSymbol,
            Map<String, String> wrapperToField) {
        if (fieldToSymbol.isEmpty()) return;
        if (hasTestAnnotation(mt)) return; // @Test methods are callsite consumers, not wrappers
        BlockTree body = mt.getBody();
        if (body == null) return;
        String foundField = findHandleInvoke(body, fieldToSymbol);
        if (foundField != null) {
            wrapperToField.put(mt.getName().toString(), foundField);
        }
    }

    /**
     * Recursively search a BlockTree for FIELD.invokeExact()/invoke().
     * Returns the field name (key of fieldToSymbol) if found, null otherwise.
     */
    private static String findHandleInvoke(BlockTree block, Map<String, String> fieldToSymbol) {
        for (StatementTree stmt : block.getStatements()) {
            String r = findHandleInvokeStmt(stmt, fieldToSymbol, 0);
            if (r != null) return r;
        }
        return null;
    }

    private static String findHandleInvokeStmt(StatementTree stmt, Map<String, String> fts, int depth) {
        if (depth > 4) return null;
        if (stmt instanceof ReturnTree rt && rt.getExpression() != null)
            return findHandleInvokeExpr(rt.getExpression(), fts, 0);
        if (stmt instanceof ExpressionStatementTree est)
            return findHandleInvokeExpr(est.getExpression(), fts, 0);
        if (stmt instanceof VariableTree vt && vt.getInitializer() != null)
            return findHandleInvokeExpr(vt.getInitializer(), fts, 0);
        if (stmt instanceof BlockTree bt)
            return findHandleInvoke(bt, fts);
        if (stmt instanceof TryTree tt)
            return findHandleInvoke(tt.getBlock(), fts);
        return null;
    }

    private static String findHandleInvokeExpr(ExpressionTree expr, Map<String, String> fts, int depth) {
        if (depth > 8 || expr == null) return null;
        expr = unwrapCast(expr);
        if (expr instanceof MethodInvocationTree mit) {
            String name = simpleName(mit);
            if (name.equals("invokeExact") || name.equals("invoke")) {
                ExpressionTree sel = mit.getMethodSelect();
                if (sel instanceof MemberSelectTree mst) {
                    ExpressionTree recv = mst.getExpression();
                    if (recv instanceof IdentifierTree id && fts.containsKey(id.getName().toString()))
                        return id.getName().toString();
                }
            }
            // Recurse into arguments
            for (ExpressionTree arg : mit.getArguments()) {
                String r = findHandleInvokeExpr(arg, fts, depth + 1);
                if (r != null) return r;
            }
            // Recurse into receiver chain
            ExpressionTree sel = mit.getMethodSelect();
            if (sel instanceof MemberSelectTree mst)
                return findHandleInvokeExpr(mst.getExpression(), fts, depth + 1);
        }
        return null;
    }

    // ── Callsite peeling (AST, no regex) ─────────────────────────────────────

    /**
     * Peel casts and single-argument wrapper calls (Math.toIntExact, etc.)
     * from the RHS of assertEquals to reveal the underlying wrapper call.
     * Depth-bounded at 4.
     */
    private static ExpressionTree peelToWrapperCall(
            ExpressionTree expr,
            Map<String, String> wrapperToField) {
        for (int d = 0; d < 4; d++) {
            expr = unwrapCast(expr);
            if (!(expr instanceof MethodInvocationTree mit)) return expr;
            String name = simpleName(mit);
            if (wrapperToField.containsKey(name)) return expr; // it's the wrapper
            // Single-argument envelope — peel it
            List<? extends ExpressionTree> args = mit.getArguments();
            if (args.size() == 1) {
                expr = args.get(0);
            } else {
                return expr;
            }
        }
        return expr;
    }

    // ── Common AST helpers ────────────────────────────────────────────────────

    /** Get simple method name from a MethodInvocationTree (no regex). */
    private static String simpleName(MethodInvocationTree mit) {
        ExpressionTree sel = mit.getMethodSelect();
        if (sel instanceof IdentifierTree   id)  return id.getName().toString();
        if (sel instanceof MemberSelectTree mst) return mst.getIdentifier().toString();
        return "";
    }

    /** Unwrap TypeCastTree layers to reveal the inner expression. */
    private static ExpressionTree unwrapCast(ExpressionTree expr) {
        while (expr instanceof TypeCastTree tct) expr = tct.getExpression();
        return expr;
    }

    /** Return true iff any annotation on this MethodTree has simple name "Test". */
    private static boolean hasTestAnnotation(MethodTree mt) {
        for (AnnotationTree ann : mt.getModifiers().getAnnotations()) {
            String n = ann.getAnnotationType().toString();
            if (n.equals("Test") || n.endsWith(".Test")) return true;
        }
        return false;
    }

    // ── #euf# name formula ────────────────────────────────────────────────────

    /**
     * Build the #euf# assertion name — identical formula to the deleted PanamaFfmLiftRpc.
     * callee = Java wrapper method name (= native symbol name, by convention in the showcase)
     * arg    = the string representation of the literal argument
     */
    private static String eufAssertionName(String callee, String arg) {
        String safe = callee.chars()
            .mapToObj(ch -> Character.isLetterOrDigit(ch) && ch < 128
                ? Character.toString((char) ch) : "_")
            .reduce("", String::concat);
        return callee + "#euf#c:callresult_" + safe + "_a1(i:" + arg + ")::assertion";
    }

    // ── Call-edge JSON — byte-identical shape to deleted lifter ───────────────

    private static String callEdgeJson(
            String sourceCid, String targetCid, String targetSymbol,
            String file, int line, int column, String caller) {
        return "{"
            + "\"callSiteLocus\":{\"column\":" + column + ",\"file\":\"" + esc(file) + "\",\"line\":" + line + "},"
            + "\"evidenceTerm\":{\"args\":[{\"kind\":\"var\",\"name\":\"" + esc(caller) + "\"}],\"kind\":\"atomic\",\"name\":\"call-site-obligation\"},"
            + "\"kind\":\"call-edge\","
            + "\"schemaVersion\":\"1\","
            + "\"sourceContractCid\":\"" + esc(sourceCid) + "\","
            + "\"targetContractCid\":\"" + esc(targetCid) + "\","
            + "\"targetSymbol\":\"" + esc(targetSymbol) + "\""
            + "}";
    }

    private static String diagnostic(String path, String reason, String detail) {
        return "{\"kind\":\"lift-gap\",\"path\":\"" + esc(path) + "\","
            + "\"reason\":\"" + esc(reason + (detail != null ? ": " + detail : "")) + "\"}";
    }

    // ── File enumeration ──────────────────────────────────────────────────────

    private static List<String> enumerateJavaFiles(Path root, List<String> sourcePaths) throws IOException {
        List<String> out = new ArrayList<>();
        for (String entry : sourcePaths) {
            Path path = root.resolve(entry).normalize();
            if (Files.isDirectory(path)) {
                try (Stream<Path> stream = Files.walk(path)) {
                    stream.filter(Files::isRegularFile)
                        .filter(p -> p.getFileName().toString().endsWith(".java"))
                        .filter(p -> !isIgnoredPath(root, p))
                        .forEach(p -> out.add(root.relativize(p).toString().replace('\\', '/')));
                }
            } else if (Files.isRegularFile(path) && path.getFileName().toString().endsWith(".java")) {
                out.add(root.relativize(path).toString().replace('\\', '/'));
            }
        }
        out.sort(Comparator.naturalOrder());
        return out;
    }

    private static boolean isIgnoredPath(Path root, Path path) {
        String rel = root.relativize(path).toString().replace('\\', '/');
        return rel.startsWith("target/") || rel.contains("/target/")
            || rel.startsWith(".sugar/") || rel.contains("/.sugar/");
    }

    // ── StringJavaFileObject ──────────────────────────────────────────────────

    private static final class StringJavaFileObject extends SimpleJavaFileObject {
        private final String content;
        StringJavaFileObject(String name, String content) {
            super(URI.create("string:///" + name.replace('\\', '/')), Kind.SOURCE);
            this.content = content;
        }
        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return content; }
    }

    // ── JSON helpers (wire codec only — never scans Java source) ─────────────

    private static List<Binding> parseContractBindings(String json) {
        List<Binding> out = new ArrayList<>();
        for (String obj : objectArray(json, "contract_bindings")) {
            Optional<String> name = jsonString(obj, "name");
            Optional<String> cid  = jsonString(obj, "contract_cid");
            if (name.isEmpty() || cid.isEmpty()) continue;
            out.add(new Binding(name.get(), cid.get(),
                jsonString(obj, "target_proof_cid").orElse(null)));
        }
        return out;
    }

    private static List<String> jsonStringArray(String json, String key) {
        int kp = json.indexOf("\"" + key + "\""); if (kp < 0) return List.of();
        int s  = json.indexOf('[', kp);            if (s  < 0) return List.of();
        int e  = matching(json, s, '[', ']');      if (e  < 0) return List.of();
        String body = json.substring(s + 1, e);
        List<String> out = new ArrayList<>();
        int i = 0;
        while (i < body.length()) {
            int q = body.indexOf('"', i); if (q < 0) break;
            StringBuilder sb = new StringBuilder(); boolean esc = false;
            int j = q + 1;
            for (; j < body.length(); j++) {
                char ch = body.charAt(j);
                if (esc) { sb.append(unescape(ch)); esc = false; }
                else if (ch == '\\') { esc = true; }
                else if (ch == '"') { break; }
                else { sb.append(ch); }
            }
            out.add(sb.toString()); i = j + 1;
        }
        return out;
    }

    private static List<String> objectArray(String json, String key) {
        int kp = json.indexOf("\"" + key + "\""); if (kp < 0) return List.of();
        int s  = json.indexOf('[', kp);            if (s  < 0) return List.of();
        int e  = matching(json, s, '[', ']');      if (e  < 0) return List.of();
        String body = json.substring(s + 1, e);
        List<String> out = new ArrayList<>();
        int idx = 0;
        while (idx < body.length()) {
            int open = body.indexOf('{', idx); if (open < 0) break;
            int close = matching(body, open, '{', '}'); if (close < 0) break;
            out.add(body.substring(open, close + 1)); idx = close + 1;
        }
        return out;
    }

    static Optional<String> jsonString(String json, String key) {
        int kp = json.indexOf("\"" + key + "\""); if (kp < 0) return Optional.empty();
        int c  = json.indexOf(':', kp);            if (c  < 0) return Optional.empty();
        int q  = json.indexOf('"', c + 1);         if (q  < 0) return Optional.empty();
        StringBuilder sb = new StringBuilder(); boolean esc = false;
        for (int i = q + 1; i < json.length(); i++) {
            char ch = json.charAt(i);
            if (esc) { sb.append(unescape(ch)); esc = false; }
            else if (ch == '\\') { esc = true; }
            else if (ch == '"') { return Optional.of(sb.toString()); }
            else { sb.append(ch); }
        }
        return Optional.empty();
    }

    private static char unescape(char ch) {
        return switch (ch) {
            case 'n' -> '\n'; case 'r' -> '\r'; case 't' -> '\t';
            case '"' -> '"';  case '\\' -> '\\'; default -> ch;
        };
    }

    private static int matching(String s, int open, char openCh, char closeCh) {
        int depth = 0; boolean inStr = false, esc = false;
        for (int i = open; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (inStr) { if (esc) esc = false; else if (ch == '\\') esc = true; else if (ch == '"') inStr = false; continue; }
            if (ch == '"') inStr = true;
            else if (ch == openCh) depth++;
            else if (ch == closeCh && --depth == 0) return i;
        }
        return -1;
    }

    private static String extractId(String json) {
        int kp = json.indexOf("\"id\""); if (kp < 0) return "null";
        int c  = json.indexOf(':', kp); if (c  < 0) return "null";
        int i = c + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) i++;
        if (i >= json.length()) return "null";
        if (json.charAt(i) == '"')
            return jsonString(json.substring(kp), "id").map(v -> "\"" + esc(v) + "\"").orElse("null");
        int start = i;
        while (i < json.length() && json.charAt(i) != ',' && json.charAt(i) != '}') i++;
        return json.substring(start, i).trim();
    }

    private static String ok(String id, String result) {
        return "{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":" + result + "}";
    }
    private static String error(String id, int code, String msg) {
        return "{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"error\":{\"code\":" + code
            + ",\"message\":\"" + esc(msg) + "\"}}";
    }
    private static String esc(String s) {
        return s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n")
                .replace("\r","\\r").replace("\t","\\t");
    }

    // ── Data records ──────────────────────────────────────────────────────────

    private record Binding(String name, String cid, String targetProofCid) {}
}
