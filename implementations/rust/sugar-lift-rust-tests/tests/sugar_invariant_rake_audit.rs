use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug)]
struct SourceFile {
    rel: String,
    text: String,
}

#[derive(Debug)]
struct Offender {
    axis: &'static str,
    file: String,
    line: usize,
    observed: String,
    fix: &'static str,
}

#[test]
fn sugar_invariant_rake_vector_is_stable_zero() {
    let manifest = manifest_dir();
    let files = production_sources(&manifest);

    let mut offenders = Vec::new();
    offenders.extend(outcome_complete_erasure(&files));
    offenders.extend(incomplete_erased_to_absence(&files));
    offenders.extend(typed_effect_erased_to_reason_string(&files));
    offenders.extend(effect_reason_branching(&files));
    offenders.extend(factory_reentry_from_reduction(&files));
    offenders.extend(absence_shaped_child_effect_helpers(&files));
    offenders.extend(stringly_child_effect_helpers(&files));

    offenders.sort_by_key(|offender| {
        (
            offender.axis,
            offender.file.clone(),
            offender.line,
            offender.observed.clone(),
        )
    });

    let mut counts = BTreeMap::<&'static str, usize>::new();
    for offender in &offenders {
        *counts.entry(offender.axis).or_default() += 1;
    }

    assert!(
        offenders.is_empty(),
        "SUGAR INVARIANT RAKE AUDIT FAILED: R={} offender(s) remain.\n\
         The type system catches most construction mistakes; this test catches the \
         agent mistakes that compile but violate docs/sugar-invariants.md.\n\
         Red is red until R == 0. Do not bless a lower threshold. Remove offenders by \
         making sugars boring typed composers and by moving behavior behind floor-owned \
         visitors.\n\n\
         R vector: {}\n\n{}",
        offenders.len(),
        render_counts(&counts),
        render_offenders(&offenders)
    );
}

fn outcome_complete_erasure(files: &[SourceFile]) -> Vec<Offender> {
    find_lines(files, "outcome_complete_erasure", |file, line| {
        if !line.code.contains(".complete()") {
            return None;
        }
        Some(Offender {
            axis: "outcome_complete_erasure",
            file: file.rel.clone(),
            line: line.number,
            observed: line.code.to_string(),
            fix: "delete the absence path: replace Outcome::complete() with an explicit match \
                  on Outcome::{Complete, Incomplete}; compose Complete and return \
                  Outcome::Incomplete(effect) unchanged for child effects",
        })
    })
}

fn incomplete_erased_to_absence(files: &[SourceFile]) -> Vec<Offender> {
    find_lines(files, "incomplete_erased_to_absence", |file, line| {
        let code = line.code;
        let erases_outcome = code.contains("Outcome::Incomplete(_)")
            && (code.contains("=> None")
                || code.contains("=> return None")
                || code.contains("=> Ok(None)")
                || code.contains("=> return Ok(None)"));
        let erases_floor_read = code.contains("FloorRead::Incomplete(_)")
            && (code.contains("=> None")
                || code.contains("=> return None")
                || code.contains("=> Ok(None)")
                || code.contains("=> return Ok(None)"));
        if !(erases_outcome || erases_floor_read) {
            return None;
        }
        Some(Offender {
            axis: "incomplete_erased_to_absence",
            file: file.rel.clone(),
            line: line.number,
            observed: code.to_string(),
            fix:
                "absence is not a third outcome: change this helper to return Result<T, Outcome> \
                  or Result<T, Effect>, and bubble the exact child effect instead of returning None",
        })
    })
}

fn typed_effect_erased_to_reason_string(files: &[SourceFile]) -> Vec<Offender> {
    find_lines(
        files,
        "typed_effect_erased_to_reason_string",
        |file, line| {
            let code = line.code;
            let erases_to_err = code.contains("Outcome::Incomplete(effect)")
                && code.contains("Err(effect.reason())");
            let captures_reason = code.contains("let reason = effect.reason();");
            if !(erases_to_err || captures_reason) {
                return None;
            }
            if is_reporting_boundary(&file.rel) {
                return None;
            }
            Some(Offender {
                axis: "typed_effect_erased_to_reason_string",
                file: file.rel.clone(),
                line: line.number,
                observed: code.to_string(),
                fix: "keep the Effect typed: return Outcome::Incomplete(effect), or change the \
                  adapter signature to carry Outcome/Effect; render effect.reason() only at \
                  report/output boundaries",
            })
        },
    )
}

fn effect_reason_branching(files: &[SourceFile]) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for file in files {
        if is_reporting_boundary(&file.rel) {
            continue;
        }
        let lines = production_lines(&file.text);
        for (idx, line) in lines.iter().enumerate() {
            let direct_branch = line.code.contains("effect.reason()")
                && (line.code.contains("==")
                    || line.code.contains(".contains(")
                    || line.code.contains("match "));
            let indirect_branch = line.code.contains("let reason = effect.reason();")
                && lines.iter().skip(idx + 1).take(4).any(|next| {
                    next.code.contains("reason.contains(")
                        || next.code.contains("reason ==")
                        || next.code.contains("match reason")
                        || next.code.contains("refusal_disposition(&reason)")
                });
            if !(direct_branch || indirect_branch) {
                continue;
            }
            offenders.push(Offender {
                axis: "effect_reason_branching",
                file: file.rel.clone(),
                line: line.number,
                observed: line.code.to_string(),
                fix: "do not branch on effect prose: add a structured Effect variant, floor \
                      visitor, or typed floor result for the case being distinguished; callers \
                      then match structure and still bubble unrelated child effects unchanged",
            });
        }
    }
    offenders
}

fn factory_reentry_from_reduction(files: &[SourceFile]) -> Vec<Offender> {
    find_lines(files, "factory_reentry_from_reduction", |file, line| {
        if !file.rel.starts_with("src/sugar/") {
            return None;
        }
        let code = line.code;
        let rebuilds_ctx_from_reduction = code.contains("SugarBuildCtx::new(ctx.scope")
            || code.contains("SugarBuildCtx::new(self.ctx.scope");
        let builds_and_reduces_immediately = (code.contains("build_term(")
            || code.contains("build_composite(")
            || code.contains("build_constraint(")
            || code.contains("build_assertion_surface("))
            && (code.contains(".desugar(ctx")
                || code.contains(".desugar(&ctx")
                || code.contains(".reduce(ctx")
                || code.contains(".reduce(&ctx"));
        if !(rebuilds_ctx_from_reduction || builds_and_reduces_immediately) {
            return None;
        }
        if file.rel == "src/sugar/factory.rs" || file.rel == "src/sugar/catalog.rs" {
            return None;
        }
        Some(Offender {
            axis: "factory_reentry_from_reduction",
            file: file.rel.clone(),
            line: line.number,
            observed: code.to_string(),
            fix: "recognition constructs the graph: store child source sites as \
                  SugarBody<TermFloor>/SugarBody<CompositeFloor>/SugarBody<...> in the sugar \
                  during construction, then reduce those bodies in desugar; if this is a \
                  synthetic bridge, isolate it behind a tiny named bridge sugar instead of \
                  reopening the factory from ordinary reduction code",
        })
    })
}

fn absence_shaped_child_effect_helpers(files: &[SourceFile]) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for file in files
        .iter()
        .filter(|file| file.rel.starts_with("src/sugar/"))
    {
        if is_reporting_boundary(&file.rel) {
            continue;
        }
        for block in function_blocks(file) {
            if !absence_shaped_return(&block.signature) {
                continue;
            }
            if !touches_child_effect_surface(&block.body) {
                continue;
            }
            offenders.push(Offender {
                axis: "absence_shaped_child_effect_helper",
                file: file.rel.clone(),
                line: block.start_line,
                observed: block.signature,
                fix: "absence is only recognizer decline or static no-match: if this helper \
                      reduces/desugars children, change the return type to Outcome, \
                      Result<T, Outcome>, or Result<T, Effect>; bubble child effects typed \
                      and panic on impossible floor/construction gaps",
            });
        }
    }
    offenders
}

fn stringly_child_effect_helpers(files: &[SourceFile]) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for file in files
        .iter()
        .filter(|file| file.rel.starts_with("src/sugar/"))
    {
        if is_reporting_boundary(&file.rel) {
            continue;
        }
        for block in function_blocks(file) {
            if !stringly_return(&block.signature) {
                continue;
            }
            if !touches_child_effect_surface(&block.body) {
                continue;
            }
            offenders.push(Offender {
                axis: "stringly_child_effect_helper",
                file: file.rel.clone(),
                line: block.start_line,
                observed: block.signature,
                fix: "typed effects stay typed: replace String error transport with Effect, \
                      Outcome, Result<T, Effect>, or Result<T, Outcome>; render \
                      effect.reason() only at a reporting boundary",
            });
        }
    }
    offenders
}

fn find_lines(
    files: &[SourceFile],
    axis: &'static str,
    mut classify: impl FnMut(&SourceFile, &CodeLine<'_>) -> Option<Offender>,
) -> Vec<Offender> {
    let mut offenders = Vec::new();
    for file in files {
        for line in production_lines(&file.text) {
            if let Some(mut offender) = classify(file, &line) {
                offender.axis = axis;
                offenders.push(offender);
            }
        }
    }
    offenders
}

#[derive(Clone, Copy)]
struct CodeLine<'a> {
    number: usize,
    code: &'a str,
}

struct FunctionBlock {
    start_line: usize,
    signature: String,
    body: String,
}

fn function_blocks(file: &SourceFile) -> Vec<FunctionBlock> {
    let mut blocks = Vec::new();
    let mut pending_cfg_test = false;
    let mut test_mod_depth = None::<i32>;
    let mut active = None::<ActiveFunction>;

    for (idx, raw) in file.text.lines().enumerate() {
        let number = idx + 1;
        let trimmed = raw.trim();
        if trimmed.starts_with("#[cfg(test)]") {
            pending_cfg_test = true;
            continue;
        }
        if pending_cfg_test && trimmed.starts_with("mod tests") {
            pending_cfg_test = false;
            let depth = raw.matches('{').count() as i32 - raw.matches('}').count() as i32;
            test_mod_depth = Some(depth.max(1));
            continue;
        }
        pending_cfg_test = false;

        if let Some(depth) = test_mod_depth.as_mut() {
            *depth += raw.matches('{').count() as i32;
            *depth -= raw.matches('}').count() as i32;
            if *depth <= 0 {
                test_mod_depth = None;
            }
            continue;
        }

        let Some(code) = strip_line_comment(raw).map(str::trim) else {
            continue;
        };
        if code.is_empty() {
            continue;
        }

        if let Some(active_fn) = active.as_mut() {
            active_fn.push(code);
            if active_fn.is_complete() {
                let done = active.take().expect("active function just completed");
                blocks.push(done.into_block());
            }
            continue;
        }

        if looks_like_fn_start(code) {
            let mut active_fn = ActiveFunction::new(number);
            active_fn.push(code);
            if active_fn.is_complete() {
                blocks.push(active_fn.into_block());
            } else {
                active = Some(active_fn);
            }
        }
    }
    blocks
}

struct ActiveFunction {
    start_line: usize,
    lines: Vec<String>,
    seen_body: bool,
    depth: i32,
}

impl ActiveFunction {
    fn new(start_line: usize) -> Self {
        Self {
            start_line,
            lines: Vec::new(),
            seen_body: false,
            depth: 0,
        }
    }

    fn push(&mut self, code: &str) {
        self.lines.push(code.to_string());
        if code.contains('{') {
            self.seen_body = true;
        }
        if self.seen_body {
            self.depth += code.matches('{').count() as i32;
            self.depth -= code.matches('}').count() as i32;
        }
    }

    fn is_complete(&self) -> bool {
        self.seen_body && self.depth <= 0
    }

    fn into_block(self) -> FunctionBlock {
        let joined = self.lines.join(" ");
        let signature = joined
            .split('{')
            .next()
            .unwrap_or(joined.as_str())
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        FunctionBlock {
            start_line: self.start_line,
            signature,
            body: joined,
        }
    }
}

fn looks_like_fn_start(code: &str) -> bool {
    code.starts_with("fn ")
        || code.starts_with("pub fn ")
        || code.starts_with("pub(crate) fn ")
        || code.starts_with("pub(super) fn ")
        || code.starts_with("pub(in ")
        || code.starts_with("async fn ")
        || code.starts_with("pub async fn ")
        || code.starts_with("pub(crate) async fn ")
        || code.starts_with("pub(super) async fn ")
}

fn absence_shaped_return(signature: &str) -> bool {
    if signature.contains("Outcome") || signature.contains("Effect") {
        return false;
    }
    let compact = compact_signature(signature);
    [
        "->Option<Desugared",
        "->Option<Rc<Term>>",
        "->Option<Vec<Expr>>",
        "->Option<Vec<DesugaredElem>>",
        "->Option<AssertionEntry>",
        "->Result<Option<",
    ]
    .iter()
    .any(|needle| compact.contains(needle))
}

fn stringly_return(signature: &str) -> bool {
    compact_signature(signature).contains("->Result<")
        && compact_signature(signature).contains("String>")
}

fn compact_signature(signature: &str) -> String {
    signature
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>()
}

fn touches_child_effect_surface(body: &str) -> bool {
    body.contains(".complete()")
        || body.contains("Outcome::Incomplete")
        || body.contains("FloorRead::Incomplete")
        || body.contains("effect.reason()")
        || body.contains(".desugar(")
        || body.contains(".reduce(")
}

fn production_lines(text: &str) -> Vec<CodeLine<'_>> {
    let mut out = Vec::new();
    let mut pending_cfg_test = false;
    let mut test_mod_depth = None::<i32>;

    for (idx, raw) in text.lines().enumerate() {
        let number = idx + 1;
        let trimmed = raw.trim();
        if trimmed.starts_with("#[cfg(test)]") {
            pending_cfg_test = true;
            continue;
        }
        if pending_cfg_test && trimmed.starts_with("mod tests") {
            pending_cfg_test = false;
            let depth = raw.matches('{').count() as i32 - raw.matches('}').count() as i32;
            test_mod_depth = Some(depth.max(1));
            continue;
        }
        pending_cfg_test = false;

        if let Some(depth) = test_mod_depth.as_mut() {
            *depth += raw.matches('{').count() as i32;
            *depth -= raw.matches('}').count() as i32;
            if *depth <= 0 {
                test_mod_depth = None;
            }
            continue;
        }

        let Some(code) = strip_line_comment(raw).map(str::trim) else {
            continue;
        };
        if code.is_empty() || code.starts_with("//") || code.starts_with("///") {
            continue;
        }
        out.push(CodeLine { number, code });
    }
    out
}

fn strip_line_comment(line: &str) -> Option<&str> {
    let trimmed = line.trim_start();
    if trimmed.starts_with("//") || trimmed.starts_with("///") || trimmed.starts_with("//!") {
        return None;
    }
    Some(line.split("//").next().unwrap_or(line))
}

fn production_sources(manifest: &Path) -> Vec<SourceFile> {
    let mut paths = rust_files(&manifest.join("src/sugar"));
    paths.push(manifest.join("src/lib.rs"));
    paths.sort();
    paths
        .into_iter()
        .map(|path| source_file(manifest, path))
        .collect()
}

fn source_file(manifest: &Path, path: PathBuf) -> SourceFile {
    let text =
        fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    SourceFile {
        rel: relative_file(&path, manifest),
        text,
    }
}

fn rust_files(root: &Path) -> Vec<PathBuf> {
    let mut files = walkdir::WalkDir::new(root)
        .max_depth(1)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file() && entry.path().extension().is_some_and(|ext| ext == "rs")
        })
        .map(|entry| entry.into_path())
        .collect::<Vec<_>>();
    files.sort();
    files
}

fn is_reporting_boundary(rel: &str) -> bool {
    matches!(
        rel,
        "src/sugar/factory.rs" | "src/sugar/catalog.rs" | "src/sugar/claim.rs" | "src/lib.rs"
    )
}

fn render_counts(counts: &BTreeMap<&'static str, usize>) -> String {
    if counts.is_empty() {
        return "[]".to_string();
    }
    counts
        .iter()
        .map(|(axis, count)| format!("{axis}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn render_offenders(offenders: &[Offender]) -> String {
    offenders
        .iter()
        .map(|offender| {
            format!(
                "- {}:{} [{}]\n  observed: {}\n  fix: {}",
                offender.file, offender.line, offender.axis, offender.observed, offender.fix
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

fn relative_file(path: &Path, root: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
