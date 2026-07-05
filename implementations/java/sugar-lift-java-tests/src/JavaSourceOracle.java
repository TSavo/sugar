// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Java Source Oracle.
//
// A SourceMemento is the compressed pointer: file + span + BLAKE3-512 CIDs.
// It never carries source text. The SourceOracle resolves that memento back to
// a SourceFragment only by reading source files and recomputing the CIDs.

import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public final class JavaSourceOracle {
    private JavaSourceOracle() {}

    public static final class SourceOracleRefusal extends Exception {
        public SourceOracleRefusal(String message) {
            super(message);
        }

        public SourceOracleRefusal(String message, Throwable cause) {
            super(message, cause);
        }
    }

    public record Span(int startLine, int startCol, int endLine, int endCol) {
        String toJson() {
            StringBuilder out = new StringBuilder();
            appendJson(out);
            return out.toString();
        }

        void appendJson(StringBuilder out) {
            out.append("{\"start_line\":").append(startLine)
                    .append(",\"start_col\":").append(startCol)
                    .append(",\"end_line\":").append(endLine)
                    .append(",\"end_col\":").append(endCol)
                    .append("}");
        }
    }

    public record SourceFragment(
            String file,
            String sourceFunctionName,
            Span span,
            List<String> paramNames,
            String bodyText,
            String templateJson,
            String sourceCid,
            String templateCid) {

        public SourceMemento toMemento() {
            return new SourceMemento(
                    file, sourceFunctionName, span, paramNames, sourceCid, templateCid);
        }
    }

    public record SourceMemento(
            String file,
            String sourceFunctionName,
            Span span,
            List<String> paramNames,
            String sourceCid,
            String templateCid) {

        public SourceMemento {
            paramNames = List.copyOf(paramNames);
        }

        public SourceMemento withSourceCid(String replacement) {
            return new SourceMemento(
                    file, sourceFunctionName, span, paramNames, replacement, templateCid);
        }

        public String toJson() {
            StringBuilder out = new StringBuilder();
            appendJson(out);
            return out.toString();
        }

        public void appendJson(StringBuilder out) {
            out.append("{");
            appendJsonFields(out);
            out.append("}");
        }

        public void appendJsonFields(StringBuilder out) {
            out.append("\"file\":\"").append(esc(file)).append("\"")
                    .append(",\"source_function_name\":\"").append(esc(sourceFunctionName)).append("\"")
                    .append(",\"span\":");
            span.appendJson(out);
            out.append(",\"source_cid\":\"").append(esc(sourceCid)).append("\"")
                    .append(",\"template_cid\":\"").append(esc(templateCid)).append("\"")
                    .append(",\"param_names\":").append(stringArrayJson(paramNames));
        }
    }

    public record SourceFragmentLocus(
            Path projectRoot,
            Path sourcePath,
            String file,
            CompilationUnitTree unit,
            MethodTree method,
            SourcePositions positions) {}

    public static SourceFragmentLocus sourceFragmentLocusForMethod(
            Path projectRoot,
            Path sourcePath,
            CompilationUnitTree unit,
            MethodTree method,
            SourcePositions positions) throws SourceOracleRefusal {
        Path root = projectRoot.toAbsolutePath().normalize();
        Path src = sourcePath.toAbsolutePath().normalize();
        if (!src.startsWith(root)) {
            throw new SourceOracleRefusal(
                    "source path `" + src + "` escapes project root `" + root + "`");
        }
        String file = root.relativize(src).toString().replace('\\', '/');
        return new SourceFragmentLocus(root, src, file, unit, method, positions);
    }

    public static SourceMemento sourceMementoOf(SourceFragmentLocus locus)
            throws SourceOracleRefusal {
        return sourceFragmentOf(locus).toMemento();
    }

    public static SourceFragment sourceFragmentOf(SourceFragmentLocus locus)
            throws SourceOracleRefusal {
        String source;
        try {
            source = Files.readString(locus.sourcePath(), StandardCharsets.UTF_8);
        } catch (IOException exc) {
            throw new SourceOracleRefusal(
                    "cannot read source `" + locus.sourcePath() + "`: " + exc.getMessage(), exc);
        }

        MethodTree method = locus.method();
        Span span = spanOf(locus.unit(), method, locus.positions());
        String bodyText = extractBodyText(source, locus.unit(), method, locus.positions());
        String templateJson = templateJson(method);
        return new SourceFragment(
                locus.file(),
                method.getName().toString(),
                span,
                paramNames(method),
                bodyText,
                templateJson,
                blake3_512Of(bodyText.getBytes(StandardCharsets.UTF_8)),
                blake3_512Of(templateJson.getBytes(StandardCharsets.UTF_8)));
    }

    public static SourceFragment resolve(Path projectRoot, SourceMemento memento)
            throws SourceOracleRefusal {
        if (memento.file() == null || memento.file().isBlank()) {
            throw new SourceOracleRefusal("source memento missing `file`");
        }

        Path root = projectRoot.toAbsolutePath().normalize();
        Path sourcePath = root.resolve(memento.file()).normalize();
        if (!sourcePath.startsWith(root)) {
            throw new SourceOracleRefusal(
                    "source memento file `" + memento.file() + "` escapes project root");
        }

        String source;
        try {
            source = Files.readString(sourcePath, StandardCharsets.UTF_8);
        } catch (IOException exc) {
            throw new SourceOracleRefusal(
                    "cannot read source `" + sourcePath + "`: " + exc.getMessage(), exc);
        }

        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            throw new SourceOracleRefusal("no JavaCompiler available");
        }

        JavaFileObject fo = new SourceStringJavaFileObject(sourcePath, source);
        JavacTask task = (JavacTask) compiler.getTask(
                null, null, d -> {}, List.of("-proc:none"), null, List.of(fo));
        Trees trees = Trees.instance(task);
        CompilationUnitTree unit;
        try {
            unit = task.parse().iterator().next();
        } catch (IOException exc) {
            throw new SourceOracleRefusal(
                    "cannot parse source `" + sourcePath + "`: " + exc.getMessage(), exc);
        }

        MethodTree method = locateMethod(unit, trees.getSourcePositions(), memento);
        if (method == null) {
            throw new SourceOracleRefusal(
                    "source function `" + memento.sourceFunctionName()
                            + "` not found in `" + memento.file() + "` near line "
                            + memento.span().startLine());
        }

        SourceFragment fragment = sourceFragmentOf(sourceFragmentLocusForMethod(
                root, sourcePath, unit, method, trees.getSourcePositions()));
        if (memento.sourceCid() != null && !memento.sourceCid().equals(fragment.sourceCid())) {
            throw new SourceOracleRefusal(
                    "source CID misaligned for `" + memento.sourceFunctionName()
                            + "` in `" + memento.file() + "`: pinned "
                            + memento.sourceCid() + ", on-disk " + fragment.sourceCid()
                            + " -- the source drifted from the proof");
        }
        if (memento.templateCid() != null && !memento.templateCid().equals(fragment.templateCid())) {
            throw new SourceOracleRefusal(
                    "template CID misaligned for `" + memento.sourceFunctionName()
                            + "` in `" + memento.file() + "`: pinned "
                            + memento.templateCid() + ", on-disk " + fragment.templateCid()
                            + " -- the AST drifted from the proof");
        }
        return fragment;
    }

    private static MethodTree locateMethod(
            CompilationUnitTree unit, SourcePositions positions, SourceMemento memento) {
        List<MethodTree> matches = new ArrayList<>();
        new TreeScanner<Void, Void>() {
            @Override public Void visitMethod(MethodTree node, Void unused) {
                if (memento.sourceFunctionName() == null
                        || node.getName().contentEquals(memento.sourceFunctionName())) {
                    matches.add(node);
                }
                return super.visitMethod(node, unused);
            }
        }.scan(unit, null);
        if (matches.isEmpty()) return null;
        if (matches.size() == 1 || memento.span() == null) return matches.get(0);

        for (MethodTree method : matches) {
            Span span = spanOf(unit, method, positions);
            if (span.startLine() <= memento.span().startLine()
                    && memento.span().startLine() <= span.endLine()) {
                return method;
            }
        }
        return matches.get(0);
    }

    private static Span spanOf(
            CompilationUnitTree unit, MethodTree method, SourcePositions positions) {
        long start = positions.getStartPosition(unit, method);
        long end = positions.getEndPosition(unit, method);
        LineMap lines = unit.getLineMap();
        return new Span(
                lineOf(lines, start),
                colOf(lines, start),
                lineOf(lines, end),
                colOf(lines, end));
    }

    private static int lineOf(LineMap lines, long pos) {
        return pos < 0 ? 0 : (int) lines.getLineNumber(pos);
    }

    private static int colOf(LineMap lines, long pos) {
        return pos < 0 ? 0 : Math.max(0, (int) lines.getColumnNumber(pos) - 1);
    }

    private static String extractBodyText(
            String source,
            CompilationUnitTree unit,
            MethodTree method,
            SourcePositions positions) throws SourceOracleRefusal {
        BlockTree body = method.getBody();
        if (body == null) return "";
        long start = positions.getStartPosition(unit, body);
        long end = positions.getEndPosition(unit, body);
        if (start < 0 || end < start || end > source.length()) {
            throw new SourceOracleRefusal(
                    "cannot locate method body for `" + method.getName() + "`");
        }
        String block = source.substring((int) start, (int) end);
        int open = block.indexOf('{');
        int close = block.lastIndexOf('}');
        if (open < 0 || close <= open) {
            return block.strip();
        }
        return dedent(block.substring(open + 1, close)).stripTrailing();
    }

    private static String dedent(String text) {
        String[] lines = text.split("\\R", -1);
        int indent = Integer.MAX_VALUE;
        for (String line : lines) {
            if (line.isBlank()) continue;
            int n = 0;
            while (n < line.length() && (line.charAt(n) == ' ' || line.charAt(n) == '\t')) n++;
            indent = Math.min(indent, n);
        }
        if (indent == Integer.MAX_VALUE || indent == 0) return text.strip();
        StringBuilder out = new StringBuilder(text.length());
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (!line.isBlank() && line.length() >= indent) out.append(line.substring(indent));
            else out.append(line.stripLeading());
            if (i + 1 < lines.length) out.append('\n');
        }
        return out.toString().strip();
    }

    private static List<String> paramNames(MethodTree method) {
        List<String> out = new ArrayList<>();
        for (VariableTree param : method.getParameters()) {
            out.add(param.getName().toString());
        }
        return List.copyOf(out);
    }

    private static String templateJson(MethodTree method) {
        StringBuilder out = new StringBuilder();
        out.append("{\"kind\":\"java-method-body\"");
        out.append(",\"param_count\":").append(method.getParameters().size());
        out.append(",\"statements\":");
        appendStatements(out, method.getBody() == null ? List.of() : method.getBody().getStatements());
        out.append("}");
        return out.toString();
    }

    private static void appendStatements(StringBuilder out, List<? extends StatementTree> statements) {
        out.append("[");
        for (int i = 0; i < statements.size(); i++) {
            if (i > 0) out.append(",");
            appendTree(out, statements.get(i));
        }
        out.append("]");
    }

    private static void appendTree(StringBuilder out, Tree tree) {
        if (tree == null) {
            out.append("null");
            return;
        }
        if (tree instanceof BlockTree block) {
            out.append("{\"kind\":\"BLOCK\",\"statements\":");
            appendStatements(out, block.getStatements());
            out.append("}");
        } else if (tree instanceof ReturnTree rt) {
            out.append("{\"kind\":\"RETURN\",\"expr\":");
            appendTree(out, rt.getExpression());
            out.append("}");
        } else if (tree instanceof ExpressionStatementTree est) {
            out.append("{\"kind\":\"EXPRESSION_STATEMENT\",\"expr\":");
            appendTree(out, est.getExpression());
            out.append("}");
        } else if (tree instanceof VariableTree vt) {
            out.append("{\"kind\":\"VARIABLE\",\"init\":");
            appendTree(out, vt.getInitializer());
            out.append("}");
        } else if (tree instanceof IfTree it) {
            out.append("{\"kind\":\"IF\",\"condition\":");
            appendTree(out, it.getCondition());
            out.append(",\"then\":");
            appendTree(out, it.getThenStatement());
            out.append(",\"else\":");
            appendTree(out, it.getElseStatement());
            out.append("}");
        } else if (tree instanceof AssignmentTree at) {
            out.append("{\"kind\":\"ASSIGNMENT\",\"variable\":");
            appendTree(out, at.getVariable());
            out.append(",\"expr\":");
            appendTree(out, at.getExpression());
            out.append("}");
        } else if (tree instanceof CompoundAssignmentTree cat) {
            out.append("{\"kind\":\"").append(cat.getKind().name()).append("\",\"variable\":");
            appendTree(out, cat.getVariable());
            out.append(",\"expr\":");
            appendTree(out, cat.getExpression());
            out.append("}");
        } else if (tree instanceof BinaryTree bt) {
            out.append("{\"kind\":\"").append(bt.getKind().name()).append("\",\"left\":");
            appendTree(out, bt.getLeftOperand());
            out.append(",\"right\":");
            appendTree(out, bt.getRightOperand());
            out.append("}");
        } else if (tree instanceof UnaryTree ut) {
            out.append("{\"kind\":\"").append(ut.getKind().name()).append("\",\"expr\":");
            appendTree(out, ut.getExpression());
            out.append("}");
        } else if (tree instanceof ParenthesizedTree pt) {
            appendTree(out, pt.getExpression());
        } else if (tree instanceof MethodInvocationTree mit) {
            out.append("{\"kind\":\"METHOD_INVOCATION\",\"select\":");
            appendTree(out, mit.getMethodSelect());
            out.append(",\"args\":");
            appendExpressions(out, mit.getArguments());
            out.append("}");
        } else if (tree instanceof NewClassTree nct) {
            out.append("{\"kind\":\"NEW_CLASS\",\"args\":");
            appendExpressions(out, nct.getArguments());
            out.append("}");
        } else if (tree instanceof MemberSelectTree mst) {
            out.append("{\"kind\":\"MEMBER_SELECT\",\"expr\":");
            appendTree(out, mst.getExpression());
            out.append("}");
        } else if (tree instanceof IdentifierTree) {
            out.append("{\"kind\":\"IDENTIFIER\"}");
        } else if (tree instanceof LiteralTree lt) {
            out.append("{\"kind\":\"LITERAL\",\"literal_kind\":\"")
                    .append(lt.getKind().name()).append("\"}");
        } else {
            out.append("{\"kind\":\"").append(tree.getKind().name()).append("\"}");
        }
    }

    private static void appendExpressions(
            StringBuilder out, List<? extends ExpressionTree> expressions) {
        out.append("[");
        for (int i = 0; i < expressions.size(); i++) {
            if (i > 0) out.append(",");
            appendTree(out, expressions.get(i));
        }
        out.append("]");
    }

    private static String blake3_512Of(byte[] bytes) {
        return JavaJunitWitnessRpc.blake3_512Of(bytes);
    }

    private static String stringArrayJson(List<String> values) {
        StringBuilder out = new StringBuilder("[");
        for (int i = 0; i < values.size(); i++) {
            if (i > 0) out.append(",");
            out.append("\"").append(esc(values.get(i))).append("\"");
        }
        out.append("]");
        return out.toString();
    }

    private static String esc(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\' -> sb.append("\\\\");
                case '"' -> sb.append("\\\"");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        return sb.toString();
    }

    private static final class SourceStringJavaFileObject extends SimpleJavaFileObject {
        private final String content;

        SourceStringJavaFileObject(Path path, String content) {
            super(path.toUri(), Kind.SOURCE);
            this.content = content;
        }

        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) {
            return content;
        }
    }
}
