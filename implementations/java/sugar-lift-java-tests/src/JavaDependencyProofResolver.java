// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Java dependency proof resolver for kit RPCs.
//
// The substrate must not inspect Maven, jars, or classpath entries directly.
// The Java kit owns that language boundary and returns opaque .proof catalog
// bytes over sugar.plugin.resolve_dependency_proofs.

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import java.util.stream.*;

final class JavaDependencyProofResolver {

    private static final String PROOF_RESOURCE_DIR = "META-INF/sugar/";

    private JavaDependencyProofResolver() {}

    static String resolveDependencyProofs(String requestJson) throws IOException {
        Path projectRoot = Path.of(jsonString(requestJson, "project_root").orElse("."))
                .toAbsolutePath()
                .normalize();

        List<ProofEntry> proofs = new ArrayList<>();
        addProjectImports(projectRoot, proofs);
        addClasspathProofs(proofs);

        proofs.sort(Comparator
                .comparing((ProofEntry p) -> p.cid == null ? "" : p.cid)
                .thenComparing(p -> p.source));

        List<ProofEntry> deduped = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (ProofEntry proof : proofs) {
            String key = (proof.cid == null ? "" : proof.cid)
                    + "\u0000" + proof.bytesBase64
                    + "\u0000" + proof.source;
            if (seen.add(key)) {
                deduped.add(proof);
            }
        }

        StringBuilder out = new StringBuilder();
        out.append("{\"proofs\":[");
        for (int i = 0; i < deduped.size(); i++) {
            if (i > 0) out.append(',');
            ProofEntry proof = deduped.get(i);
            out.append('{');
            if (proof.cid != null) {
                out.append("\"cid\":\"").append(esc(proof.cid)).append("\",");
            }
            out.append("\"bytes_base64\":\"").append(esc(proof.bytesBase64)).append("\",");
            out.append("\"source\":\"").append(esc(proof.source)).append("\"");
            out.append('}');
        }
        out.append("]}");
        return out.toString();
    }

    private static void addProjectImports(Path projectRoot, List<ProofEntry> proofs)
            throws IOException {
        Path imports = projectRoot.resolve(".sugar").resolve("imports");
        if (!Files.isDirectory(imports)) return;
        List<Path> paths;
        try (Stream<Path> stream = Files.list(imports)) {
            paths = stream
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().endsWith(".proof"))
                    .sorted()
                    .toList();
        }
        for (Path path : paths) {
            String fileName = path.getFileName().toString();
            proofs.add(proofEntry(
                    cidFromProofName(fileName),
                    Files.readAllBytes(path),
                    "sugar-imports:" + fileName));
        }
    }

    private static void addClasspathProofs(List<ProofEntry> proofs) throws IOException {
        String classPath = System.getProperty("java.class.path", "");
        if (classPath.isBlank()) return;
        String[] entries = classPath.split(java.io.File.pathSeparator);
        for (String entry : entries) {
            if (entry == null || entry.isBlank()) continue;
            Path path = Path.of(entry).toAbsolutePath().normalize();
            if (Files.isDirectory(path)) {
                addClasspathDirectory(path, proofs);
            } else if (Files.isRegularFile(path) && path.getFileName().toString().endsWith(".jar")) {
                addClasspathJar(path, proofs);
            }
        }
    }

    private static void addClasspathDirectory(Path classpathDir, List<ProofEntry> proofs)
            throws IOException {
        Path proofDir = classpathDir.resolve(PROOF_RESOURCE_DIR);
        if (!Files.isDirectory(proofDir)) return;
        List<Path> paths;
        try (Stream<Path> stream = Files.list(proofDir)) {
            paths = stream
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().endsWith(".proof"))
                    .sorted()
                    .toList();
        }
        for (Path path : paths) {
            String fileName = path.getFileName().toString();
            String resource = PROOF_RESOURCE_DIR + fileName;
            proofs.add(proofEntry(
                    cidFromProofName(fileName),
                    Files.readAllBytes(path),
                    "classpath:" + classpathDir + "!" + resource));
        }
    }

    private static void addClasspathJar(Path jarPath, List<ProofEntry> proofs)
            throws IOException {
        try (JarFile jar = new JarFile(jarPath.toFile())) {
            List<JarEntry> entries = jar.stream()
                    .filter(entry -> !entry.isDirectory())
                    .filter(entry -> entry.getName().startsWith(PROOF_RESOURCE_DIR))
                    .filter(entry -> entry.getName().endsWith(".proof"))
                    .sorted(Comparator.comparing(JarEntry::getName))
                    .toList();
            for (JarEntry entry : entries) {
                byte[] bytes;
                try (InputStream input = jar.getInputStream(entry)) {
                    bytes = input.readAllBytes();
                }
                proofs.add(proofEntry(
                        cidFromProofName(entry.getName()),
                        bytes,
                        "classpath:" + jarPath + "!" + entry.getName()));
            }
        }
    }

    private static ProofEntry proofEntry(String cid, byte[] bytes, String source) {
        return new ProofEntry(
                cid,
                Base64.getEncoder().encodeToString(bytes),
                source);
    }

    private static String cidFromProofName(String name) {
        int slash = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
        String base = slash >= 0 ? name.substring(slash + 1) : name;
        if (!base.endsWith(".proof")) return null;
        String cid = base.substring(0, base.length() - ".proof".length());
        return cid.startsWith("blake3-512:") ? cid : null;
    }

    private static Optional<String> jsonString(String json, String key) {
        int kp = json.indexOf("\"" + key + "\"");
        if (kp < 0) return Optional.empty();
        int c = json.indexOf(':', kp);
        if (c < 0) return Optional.empty();
        int q = json.indexOf('"', c + 1);
        if (q < 0) return Optional.empty();
        StringBuilder sb = new StringBuilder();
        boolean escaped = false;
        for (int i = q + 1; i < json.length(); i++) {
            char ch = json.charAt(i);
            if (escaped) {
                sb.append(unescape(ch));
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                return Optional.of(sb.toString());
            } else {
                sb.append(ch);
            }
        }
        return Optional.empty();
    }

    private static char unescape(char ch) {
        return switch (ch) {
            case 'n' -> '\n';
            case 'r' -> '\r';
            case 't' -> '\t';
            case '"' -> '"';
            case '\\' -> '\\';
            default -> ch;
        };
    }

    private static String esc(String s) {
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    private record ProofEntry(String cid, String bytesBase64, String source) {}
}
