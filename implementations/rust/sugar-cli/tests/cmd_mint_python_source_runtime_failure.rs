// SPDX-License-Identifier: Apache-2.0

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::{json, Value as Json};
use sugar_verifier::ObligationVerdict;

const RUNTIME_FAILURE_SITE: &str = "concept:panic-freedom.leaf.runtime-failure-site";

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn python_source_lift_src() -> PathBuf {
    repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-python-source")
        .join("src")
}

fn python_tests_lift_src() -> PathBuf {
    repo_root()
        .join("implementations")
        .join("python")
        .join("sugar-lift-py-tests")
        .join("src")
}

fn shell_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn python_available() -> bool {
    Command::new("python3")
        .arg("--version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn unique_dir(suffix: &str) -> PathBuf {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let p = std::env::temp_dir().join(format!("sugar-py-source-runtime-{stamp}-{suffix}"));
    fs::create_dir_all(&p).expect("mkdir");
    p
}

fn write_executable(path: &Path, body: &str) {
    use std::io::Write as _;
    {
        let mut file = fs::File::create(path).expect("create script");
        file.write_all(body.as_bytes()).expect("write script");
        file.sync_all().expect("sync script");
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path).expect("stat script").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod script");
    }
}

fn build_python_lift_source() -> PathBuf {
    let python_source = python_source_lift_src()
        .into_os_string()
        .into_string()
        .expect("Python lift source root must be UTF-8");
    let python_tests = python_tests_lift_src()
        .into_os_string()
        .into_string()
        .expect("Python tests lift source root must be UTF-8");
    let pythonpath = format!("{python_source}:{python_tests}");
    let quoted_pythonpath = shell_single_quote(&pythonpath);
    let script_dir = unique_dir("lift-script");
    let script = script_dir.join("sugar-lift-python-source.sh");
    let body = format!(
        "#!/bin/sh\nPYTHON=${{PYTHON:-python3}}\n\
         PYTHONPATH={quoted_pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}\n\
         export PYTHONPATH\n\
         exec \"$PYTHON\" -c \"from sugar_lift_python_source.rpc import run_rpc; run_rpc()\"\n"
    );
    write_executable(&script, &body);
    script
}

fn output_retrying_etxtbsy(cmd: &mut Command) -> std::process::Output {
    const MAX_ATTEMPTS: u32 = 5;
    for attempt in 0..MAX_ATTEMPTS {
        let out = cmd.output().expect("spawn sugar mint");
        let stderr = String::from_utf8_lossy(&out.stderr);
        let is_etxtbsy = !out.status.success()
            && (stderr.contains("Text file busy") || stderr.contains("os error 26"));
        if !is_etxtbsy {
            return out;
        }
        std::thread::sleep(std::time::Duration::from_millis(
            20 * u64::from(attempt + 1),
        ));
    }
    cmd.output().expect("spawn sugar mint (final attempt)")
}

fn stage_python_source_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("project");
    fs::write(
        project.join("boom.py"),
        "def boom():\n    raise ValueError\n",
    )
    .expect("write boom.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_access_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("access-project");
    fs::write(
        project.join("access.py"),
        "def use(obj, xs, key):\n    attr = obj.name\n    item = xs[key]\n    return attr\n",
    )
    .expect("write access.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_classshape_project(lift_script: &Path, source: &str) -> PathBuf {
    let project = unique_dir("classshape-project");
    fs::write(project.join("classshape.py"), source).expect("write classshape.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_store_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("store-project");
    fs::write(
        project.join("store.py"),
        "def write(obj, xs, ys, i, key, value):\n    obj.name = value\n    xs[key] = value\n    obj.inner.name = value\n    xs[ys[i]] = value\n    return value\n",
    )
    .expect("write store.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_slice_assign_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("slice-assign-project");
    fs::write(
        project.join("slice.py"),
        "def slice_write(obj, xs, a, b, c, value):\n    xs[a:b] = value\n    xs[a:b:c] = value\n    xs[:b] = value\n    xs[a:] = value\n    xs[:] = value\n    obj.inner[a:b] = value\n    xs[obj.i:obj.j] = value\n    return value\n",
    )
    .expect("write slice.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_slice_access_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("slice-access-project");
    fs::write(
        project.join("slice_access.py"),
        "def slice_read(obj, xs, a, b, c):\n    basic = xs[a:b]\n    stepped = xs[a:b:c]\n    lower = xs[:b]\n    upper = xs[a:]\n    all_items = xs[:]\n    nested = obj.inner[a:b]\n    bounded = xs[obj.i:obj.j]\n    return bounded\n",
    )
    .expect("write slice_access.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_slice_augassign_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("slice-augassign-project");
    fs::write(
        project.join("slice_augassign.py"),
        "def slice_bump(obj, xs, a, b, c, value):\n    xs[a:b] += value\n    xs[a:b:c] += value\n    xs[:b] += value\n    xs[a:] += value\n    xs[:] += value\n    obj.inner[a:b] += value\n    xs[obj.i:obj.j] += value\n    return value\n",
    )
    .expect("write slice_augassign.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_slice_annassign_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("slice-annassign-project");
    fs::write(
        project.join("slice_annassign.py"),
        "def slice_annotate(obj, xs, a, b, c, value):\n    xs[a:b]: int\n    xs[a:b]: int = value\n    xs[a:b:c]: int\n    xs[a:b:c]: int = value\n    xs[:b]: int\n    xs[:b]: int = value\n    xs[a:]: int\n    xs[a:]: int = value\n    xs[:]: int\n    xs[:]: int = value\n    obj.inner[a:b]: int\n    obj.inner[a:b]: int = value\n    xs[obj.i:obj.j]: int\n    xs[obj.i:obj.j]: int = value\n    return value\n",
    )
    .expect("write slice_annassign.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_walrus_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("walrus-project");
    fs::write(
        project.join("walrus.py"),
        "def capture(obj, xs, key, a, b):\n    literal = (local := 42)\n    name = (same := literal)\n    attr = (x := obj.name)\n    item = (y := xs[key])\n    slice_value = (z := xs[a:b])\n    if (guard := obj.flag):\n        return attr\n    while (line := xs[key]):\n        return line\n    return slice_value\n",
    )
    .expect("write walrus.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_unpack_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("unpack-project");
    fs::write(
        project.join("unpack.py"),
        "def unpack(obj, xs, key, i, j, pair, triple):\n    a, b = pair\n    [c, d] = pair\n    x, y, z = triple\n    m, n = obj.pair\n    p, q = xs[key]\n    r, s = xs[i:j]\n    return r\n",
    )
    .expect("write unpack.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_augassign_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("augassign-project");
    fs::write(
        project.join("augassign.py"),
        "def bump(obj, xs, ys, i, key, value):\n    obj.name += value\n    xs[key] += value\n    obj.inner.name += value\n    xs[ys[i]] += value\n    return value\n",
    )
    .expect("write augassign.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn stage_python_annassign_project(lift_script: &Path) -> PathBuf {
    let project = unique_dir("annassign-project");
    fs::write(
        project.join("annassign.py"),
        "def annotate(obj, xs, ys, i, key, value, make):\n    obj.name: int\n    xs[key]: int\n    obj.name: int = value\n    xs[key]: int = value\n    obj.inner.name: int\n    xs[ys[i]]: int\n    obj.inner.name: int = value\n    xs[ys[i]]: int = value\n    make().name: int\n    return value\n",
    )
    .expect("write annassign.py");

    let sugar = project.join(".sugar");
    fs::create_dir_all(sugar.join("lift").join("python-source"))
        .expect("mkdir .sugar/lift/python-source");
    fs::write(
        sugar.join("config.toml"),
        r#"[[plugins]]
name = "python-source"
kind = "lift"
surface = "python-source"
"#,
    )
    .expect("write config.toml");
    fs::write(
        sugar
            .join("lift")
            .join("python-source")
            .join("manifest.toml"),
        format!(
            r#"name = "python-source"
version = "0.1.0-draft"
protocol_version = "sugar-lift/1"
kind = "lift"
command = ["{}", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["python-source"]
ir_version = "v1.1.0"
emits_signed_mementos = false
"#,
            lift_script.display()
        ),
    )
    .expect("write manifest.toml");

    project
}

fn run_mint(project: &Path) {
    let mut cmd = Command::new(sugar_bin());
    cmd.arg("mint")
        .arg("--project")
        .arg(project)
        .arg("--out")
        .arg(project)
        .arg("--quiet");
    let out = output_retrying_etxtbsy(&mut cmd);
    assert!(
        out.status.success(),
        "sugar mint must succeed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
}

fn contract_runtime_failure_loci(pool: &sugar_verifier::types::MementoPool) -> Vec<Json> {
    pool.mementos
        .iter()
        .filter(|(cid, _)| pool.member_kind(cid) == Some("contract"))
        .filter_map(|(cid, _)| {
            pool.member_field(cid, "panicLoci")
                .and_then(|v| v.as_array())
                .map(|a| a.to_vec())
        })
        .flat_map(|items| items.into_iter())
        .collect()
}

fn ir_var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn ir_str(value: &str) -> Json {
    json!({"kind": "const", "value": value, "sort": {"kind": "primitive", "name": "String"}})
}

fn ir_none() -> Json {
    json!({"kind": "const", "value": null, "sort": {"kind": "primitive", "name": "Unit"}})
}

fn ir_attr(value: Json, name: &str) -> Json {
    json!({"kind": "ctor", "name": "python:attribute", "args": [value, ir_str(name)]})
}

fn ir_slice(lower: Json, upper: Json, step: Json) -> Json {
    json!({"kind": "ctor", "name": "python:slice", "args": [lower, upper, step]})
}

fn ir_subscript(value: Json, index: Json) -> Json {
    json!({"kind": "ctor", "name": "python:subscript", "args": [value, index]})
}

fn ir_unpack_targets(targets: Vec<Json>) -> Json {
    json!({"kind": "ctor", "name": "python:unpack_targets", "args": targets})
}

fn ir_unpack_assign(kind: &str, targets: Vec<Json>, value: Json) -> Json {
    json!({
        "kind": "ctor",
        "name": "python:unpack_assign",
        "args": [ir_str(kind), ir_unpack_targets(targets), value]
    })
}

#[test]
fn python_source_raise_mint_preserves_runtime_failure_locus_and_enumerates_callsite() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python-source runtime-failure mint test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_source_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source proof must load cleanly: {:?}",
        pool.load_errors
    );

    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![json!({
            "effectKind": "panic-freedom",
            "callee": RUNTIME_FAILURE_SITE,
            "subkind": "explicit-raise",
            "exceptionClass": "ValueError",
            "argTerm": {"kind": "var", "name": "ValueError"},
            "file": "boom.py",
            "line": 2,
            "col": 4
        })],
        "mint must preserve the python-source runtime-failure panicLoci row"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        1,
        "verifier must surface exactly one substrate runtime-failure panic site; got {callsites:#?}"
    );
    assert_eq!(runtime_failure_sites[0].file.as_deref(), Some("boom.py"));
    assert_eq!(runtime_failure_sites[0].line, Some(2));
    assert!(
        runtime_failure_sites[0].bridge_target_cid.is_none(),
        "no bridge exists yet, so the surfaced callsite must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_access_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python-source access runtime-failure mint test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_access_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source access proof must load cleanly: {:?}",
        pool.load_errors
    );

    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "access.py",
                "line": 2,
                "col": 11
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {"kind": "var", "name": "key"}
                    ]
                },
                "file": "access.py",
                "line": 3,
                "col": 11
            }),
        ],
        "mint must preserve python-source access runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        2,
        "verifier must surface exactly two substrate runtime-failure panic sites; got {callsites:#?}"
    );
    assert_eq!(runtime_failure_sites[0].file.as_deref(), Some("access.py"));
    assert_eq!(runtime_failure_sites[0].line, Some(2));
    assert_eq!(runtime_failure_sites[1].file.as_deref(), Some("access.py"));
    assert_eq!(runtime_failure_sites[1].line, Some(3));
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.bridge_target_cid.is_none()),
        "no bridges exist yet, so surfaced access callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_classshape_attribute_safety_discharges_only_guaranteed_attribute() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python classshape discharge test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_classshape_project(
        &lift_script,
        "class Box:\n    value = 1\n\n    def read(self):\n        return self.value\n",
    );
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.class_shapes_by_class.contains_key("classshape.Box"),
        "minted proof must preserve the classShapes catalog for verifier discharge"
    );
    let report = sugar_verifier::Runner::new(sugar_verifier::RunnerConfig {
        project_root: project.clone(),
        z3_path: "z3".to_string(),
        ..Default::default()
    })
    .run();
    assert_eq!(
        report.total_callsites, 1,
        "expected one attribute-safety obligation: {report:#?}"
    );
    assert_eq!(
        report.discharged, 1,
        "guaranteed attr should discharge: {report:#?}"
    );
    assert_eq!(
        report.violations, 0,
        "guaranteed attr must not leave residue: {report:#?}"
    );
    let row = &report.rows[0];
    assert!(row.callsite.attribute_safety.is_some());
    assert_eq!(row.discharge_method.as_deref(), Some("panic-safe"));
    assert!(
        row.reason.contains("classShapes guaranteed-present"),
        "discharge reason must name the classShapes guarantee: {}",
        row.reason
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_classshape_open_attribute_stays_unproven_falsepass_guard() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python classshape falsePass guard test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_classshape_project(
        &lift_script,
        "class Box:\n    value = 1\n\n    def read(self):\n        return self.late\n",
    );
    run_mint(&project);

    let report = sugar_verifier::Runner::new(sugar_verifier::RunnerConfig {
        project_root: project.clone(),
        z3_path: "z3".to_string(),
        ..Default::default()
    })
    .run();
    assert_eq!(
        report.total_callsites, 1,
        "expected one attribute-safety obligation: {report:#?}"
    );
    assert_eq!(
        report.discharged, 0,
        "non-guaranteed attr must not discharge: {report:#?}"
    );
    assert_eq!(
        report.violations, 1,
        "non-guaranteed attr must be loudly unproven: {report:#?}"
    );
    assert_eq!(report.rows[0].status, ObligationVerdict::Undecidable);
    assert!(
        report.rows[0].reason.contains("not a guaranteed-present"),
        "falsePass guard should fail for the classShapes reason, got {}",
        report.rows[0].reason
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_store_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python-source store runtime-failure mint test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_store_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source store proof must load cleanly: {:?}",
        pool.load_errors
    );

    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "store.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {"kind": "var", "name": "key"}
                    ]
                },
                "file": "store.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "store.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {
                            "kind": "ctor",
                            "name": "python:attribute",
                            "args": [
                                {"kind": "var", "name": "obj"},
                                {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                            ]
                        },
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "store.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "ys"},
                        {"kind": "var", "name": "i"}
                    ]
                },
                "file": "store.py",
                "line": 5,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {
                            "kind": "ctor",
                            "name": "python:subscript",
                            "args": [
                                {"kind": "var", "name": "ys"},
                                {"kind": "var", "name": "i"}
                            ]
                        }
                    ]
                },
                "file": "store.py",
                "line": 5,
                "col": 4
            }),
        ],
        "mint must preserve python-source store runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        6,
        "verifier must surface exactly six substrate runtime-failure panic sites; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("store.py")),
        "all surfaced Store callsites must preserve store.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(4), true),
            (Some(5), true),
            (Some(5), true),
        ],
        "no bridges exist yet, so surfaced store callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_slice_assign_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source slice Assign runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_slice_assign_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source slice Assign proof must load cleanly: {:?}",
        pool.load_errors
    );

    let obj_inner = ir_attr(ir_var("obj"), "inner");
    let obj_i = ir_attr(ir_var("obj"), "i");
    let obj_j = ir_attr(ir_var("obj"), "j");
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_none())),
                "file": "slice.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_var("c"))),
                "file": "slice.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_var("b"), ir_none())),
                "file": "slice.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_none(), ir_none())),
                "file": "slice.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_none(), ir_none())),
                "file": "slice.py",
                "line": 6,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_inner,
                "file": "slice.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_attr(ir_var("obj"), "inner"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "slice.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_i,
                "file": "slice.py",
                "line": 8,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_j,
                "file": "slice.py",
                "line": 8,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_attr(ir_var("obj"), "i"), ir_attr(ir_var("obj"), "j"), ir_none())
                ),
                "file": "slice.py",
                "line": 8,
                "col": 4
            }),
        ],
        "mint must preserve python-source slice Assign runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        10,
        "verifier must surface exactly ten slice Assign runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("slice.py")),
        "all surfaced slice Assign callsites must preserve slice.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(5), true),
            (Some(6), true),
            (Some(7), true),
            (Some(7), true),
            (Some(8), true),
            (Some(8), true),
            (Some(8), true),
        ],
        "no bridges exist yet, so surfaced slice Assign callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_slice_access_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source slice Load runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_slice_access_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source slice Load proof must load cleanly: {:?}",
        pool.load_errors
    );

    let obj_inner = ir_attr(ir_var("obj"), "inner");
    let obj_i = ir_attr(ir_var("obj"), "i");
    let obj_j = ir_attr(ir_var("obj"), "j");
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_none())),
                "file": "slice_access.py",
                "line": 2,
                "col": 12
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_var("c"))),
                "file": "slice_access.py",
                "line": 3,
                "col": 14
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_var("b"), ir_none())),
                "file": "slice_access.py",
                "line": 4,
                "col": 12
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_none(), ir_none())),
                "file": "slice_access.py",
                "line": 5,
                "col": 12
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_none(), ir_none())),
                "file": "slice_access.py",
                "line": 6,
                "col": 16
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_inner,
                "file": "slice_access.py",
                "line": 7,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(
                    ir_attr(ir_var("obj"), "inner"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "slice_access.py",
                "line": 7,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_i,
                "file": "slice_access.py",
                "line": 8,
                "col": 17
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_j,
                "file": "slice_access.py",
                "line": 8,
                "col": 23
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_attr(ir_var("obj"), "i"), ir_attr(ir_var("obj"), "j"), ir_none())
                ),
                "file": "slice_access.py",
                "line": 8,
                "col": 14
            }),
        ],
        "mint must preserve python-source slice Load runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        10,
        "verifier must surface exactly ten slice Load runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("slice_access.py")),
        "all surfaced slice Load callsites must preserve slice_access.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(5), true),
            (Some(6), true),
            (Some(7), true),
            (Some(7), true),
            (Some(8), true),
            (Some(8), true),
            (Some(8), true),
        ],
        "no bridges exist yet, so surfaced slice Load callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_slice_augassign_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source slice AugAssign runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_slice_augassign_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source slice AugAssign proof must load cleanly: {:?}",
        pool.load_errors
    );

    let obj_inner = ir_attr(ir_var("obj"), "inner");
    let obj_i = ir_attr(ir_var("obj"), "i");
    let obj_j = ir_attr(ir_var("obj"), "j");
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_none())),
                "file": "slice_augassign.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_none())),
                "file": "slice_augassign.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_var("c"))),
                "file": "slice_augassign.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_var("c"))),
                "file": "slice_augassign.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_var("b"), ir_none())),
                "file": "slice_augassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_var("b"), ir_none())),
                "file": "slice_augassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_none(), ir_none())),
                "file": "slice_augassign.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_none(), ir_none())),
                "file": "slice_augassign.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_none(), ir_none())),
                "file": "slice_augassign.py",
                "line": 6,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_none(), ir_none())),
                "file": "slice_augassign.py",
                "line": 6,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_inner,
                "file": "slice_augassign.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(
                    ir_attr(ir_var("obj"), "inner"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "slice_augassign.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_attr(ir_var("obj"), "inner"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "slice_augassign.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_i,
                "file": "slice_augassign.py",
                "line": 8,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_j,
                "file": "slice_augassign.py",
                "line": 8,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_attr(ir_var("obj"), "i"), ir_attr(ir_var("obj"), "j"), ir_none())
                ),
                "file": "slice_augassign.py",
                "line": 8,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_attr(ir_var("obj"), "i"), ir_attr(ir_var("obj"), "j"), ir_none())
                ),
                "file": "slice_augassign.py",
                "line": 8,
                "col": 4
            }),
        ],
        "mint must preserve python-source slice AugAssign runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    // The proof keeps all seventeen panicLoci rows above. CallSite enumeration
    // deduplicates access/write rows that share callee, file, line, and
    // argTerm because CallSite does not carry panicLoci subkind (#1839).
    assert_eq!(
        runtime_failure_sites.len(),
        10,
        "verifier currently surfaces ten unique slice AugAssign runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("slice_augassign.py")),
        "all surfaced slice AugAssign callsites must preserve slice_augassign.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(5), true),
            (Some(6), true),
            (Some(7), true),
            (Some(7), true),
            (Some(8), true),
            (Some(8), true),
            (Some(8), true),
        ],
        "no bridges exist yet, so surfaced slice AugAssign callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_slice_annassign_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source slice AnnAssign runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_slice_annassign_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source slice AnnAssign proof must load cleanly: {:?}",
        pool.load_errors
    );

    let obj_inner = ir_attr(ir_var("obj"), "inner");
    let obj_i = ir_attr(ir_var("obj"), "i");
    let obj_j = ir_attr(ir_var("obj"), "j");
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_none())),
                "file": "slice_annassign.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_var("b"), ir_var("c"))),
                "file": "slice_annassign.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_var("b"), ir_none())),
                "file": "slice_annassign.py",
                "line": 7,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_var("a"), ir_none(), ir_none())),
                "file": "slice_annassign.py",
                "line": 9,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(ir_var("xs"), ir_slice(ir_none(), ir_none(), ir_none())),
                "file": "slice_annassign.py",
                "line": 11,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_inner,
                "file": "slice_annassign.py",
                "line": 12,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": ir_attr(ir_var("obj"), "inner"),
                "file": "slice_annassign.py",
                "line": 13,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_attr(ir_var("obj"), "inner"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "slice_annassign.py",
                "line": 13,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_i,
                "file": "slice_annassign.py",
                "line": 14,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_j,
                "file": "slice_annassign.py",
                "line": 14,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": ir_attr(ir_var("obj"), "i"),
                "file": "slice_annassign.py",
                "line": 15,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": ir_attr(ir_var("obj"), "j"),
                "file": "slice_annassign.py",
                "line": 15,
                "col": 13
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_attr(ir_var("obj"), "i"), ir_attr(ir_var("obj"), "j"), ir_none())
                ),
                "file": "slice_annassign.py",
                "line": 15,
                "col": 4
            }),
        ],
        "mint must preserve python-source slice AnnAssign runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    // Unlike slice AugAssign, AnnAssign never emits a paired final
    // subscript-access row. The thirteen panicLoci rows above therefore surface
    // as thirteen unique CallSites without the #1839 access/write collapse.
    assert_eq!(
        runtime_failure_sites.len(),
        13,
        "verifier must surface thirteen slice AnnAssign runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("slice_annassign.py")),
        "all surfaced slice AnnAssign callsites must preserve slice_annassign.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(3), true),
            (Some(5), true),
            (Some(7), true),
            (Some(9), true),
            (Some(11), true),
            (Some(12), true),
            (Some(13), true),
            (Some(13), true),
            (Some(14), true),
            (Some(14), true),
            (Some(15), true),
            (Some(15), true),
            (Some(15), true),
        ],
        "no bridges exist yet, so surfaced slice AnnAssign callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_walrus_mint_preserves_rhs_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python-source walrus runtime-failure mint test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_walrus_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source walrus proof must load cleanly: {:?}",
        pool.load_errors
    );

    let xs_key = ir_subscript(ir_var("xs"), ir_var("key"));
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": ir_attr(ir_var("obj"), "name"),
                "file": "walrus.py",
                "line": 4,
                "col": 17
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": xs_key,
                "file": "walrus.py",
                "line": 5,
                "col": 17
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(
                    ir_var("xs"),
                    ir_slice(ir_var("a"), ir_var("b"), ir_none())
                ),
                "file": "walrus.py",
                "line": 6,
                "col": 24
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": ir_attr(ir_var("obj"), "flag"),
                "file": "walrus.py",
                "line": 7,
                "col": 17
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": ir_subscript(ir_var("xs"), ir_var("key")),
                "file": "walrus.py",
                "line": 9,
                "col": 19
            }),
        ],
        "mint must preserve python-source walrus RHS runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        5,
        "verifier must surface five walrus RHS runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("walrus.py")),
        "all surfaced walrus callsites must preserve walrus.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(4), true),
            (Some(5), true),
            (Some(6), true),
            (Some(7), true),
            (Some(9), true),
        ],
        "no bridges exist yet, so surfaced walrus callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_unpack_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!("python3 not on PATH: skipping python-source unpack runtime-failure mint test");
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_unpack_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source unpack proof must load cleanly: {:?}",
        pool.load_errors
    );

    let tuple_pair = ir_unpack_assign("tuple", vec![ir_var("a"), ir_var("b")], ir_var("pair"));
    let list_pair = ir_unpack_assign("list", vec![ir_var("c"), ir_var("d")], ir_var("pair"));
    let tuple_triple = ir_unpack_assign(
        "tuple",
        vec![ir_var("x"), ir_var("y"), ir_var("z")],
        ir_var("triple"),
    );
    let obj_pair = ir_attr(ir_var("obj"), "pair");
    let tuple_obj_pair =
        ir_unpack_assign("tuple", vec![ir_var("m"), ir_var("n")], obj_pair.clone());
    let xs_key = ir_subscript(ir_var("xs"), ir_var("key"));
    let tuple_xs_key = ir_unpack_assign("tuple", vec![ir_var("p"), ir_var("q")], xs_key.clone());
    let xs_slice = ir_subscript(ir_var("xs"), ir_slice(ir_var("i"), ir_var("j"), ir_none()));
    let tuple_xs_slice =
        ir_unpack_assign("tuple", vec![ir_var("r"), ir_var("s")], xs_slice.clone());
    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": tuple_pair,
                "file": "unpack.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": list_pair,
                "file": "unpack.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": tuple_triple,
                "file": "unpack.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": obj_pair,
                "file": "unpack.py",
                "line": 5,
                "col": 11
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": tuple_obj_pair,
                "file": "unpack.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": xs_key,
                "file": "unpack.py",
                "line": 6,
                "col": 11
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": tuple_xs_key,
                "file": "unpack.py",
                "line": 6,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": xs_slice,
                "file": "unpack.py",
                "line": 7,
                "col": 11
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "iter-unpack",
                "argTerm": tuple_xs_slice,
                "file": "unpack.py",
                "line": 7,
                "col": 4
            }),
        ],
        "mint must preserve python-source unpack runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        9,
        "verifier must surface nine unpack runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("unpack.py")),
        "all surfaced unpack callsites must preserve unpack.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(5), true),
            (Some(5), true),
            (Some(6), true),
            (Some(6), true),
            (Some(7), true),
            (Some(7), true),
        ],
        "no bridges exist yet, so surfaced unpack callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_augassign_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source AugAssign runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_augassign_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source AugAssign proof must load cleanly: {:?}",
        pool.load_errors
    );

    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "augassign.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "augassign.py",
                "line": 2,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {"kind": "var", "name": "key"}
                    ]
                },
                "file": "augassign.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {"kind": "var", "name": "key"}
                    ]
                },
                "file": "augassign.py",
                "line": 3,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "augassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {
                            "kind": "ctor",
                            "name": "python:attribute",
                            "args": [
                                {"kind": "var", "name": "obj"},
                                {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                            ]
                        },
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "augassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {
                            "kind": "ctor",
                            "name": "python:attribute",
                            "args": [
                                {"kind": "var", "name": "obj"},
                                {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                            ]
                        },
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "augassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "ys"},
                        {"kind": "var", "name": "i"}
                    ]
                },
                "file": "augassign.py",
                "line": 5,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {
                            "kind": "ctor",
                            "name": "python:subscript",
                            "args": [
                                {"kind": "var", "name": "ys"},
                                {"kind": "var", "name": "i"}
                            ]
                        }
                    ]
                },
                "file": "augassign.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {
                            "kind": "ctor",
                            "name": "python:subscript",
                            "args": [
                                {"kind": "var", "name": "ys"},
                                {"kind": "var", "name": "i"}
                            ]
                        }
                    ]
                },
                "file": "augassign.py",
                "line": 5,
                "col": 4
            }),
        ],
        "mint must preserve python-source AugAssign runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    // The proof keeps all ten panicLoci rows above. CallSite enumeration
    // currently deduplicates access/write rows that share callee, file, line,
    // and argTerm because CallSite does not carry panicLoci subkind.
    assert_eq!(
        runtime_failure_sites.len(),
        6,
        "verifier currently surfaces six unique AugAssign runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("augassign.py")),
        "all surfaced AugAssign callsites must preserve augassign.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(2), true),
            (Some(3), true),
            (Some(4), true),
            (Some(4), true),
            (Some(5), true),
            (Some(5), true),
        ],
        "no bridges exist yet, so surfaced AugAssign callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}

#[test]
fn python_source_annassign_mint_preserves_runtime_failure_loci_and_enumerates_callsites() {
    if !python_available() {
        eprintln!(
            "python3 not on PATH: skipping python-source AnnAssign runtime-failure mint test"
        );
        return;
    }
    let lift_script = build_python_lift_source();
    let project = stage_python_annassign_project(&lift_script);
    run_mint(&project);

    let pool = sugar_verifier::load_all_proofs::run(&project);
    assert!(
        pool.load_errors.is_empty(),
        "python-source AnnAssign proof must load cleanly: {:?}",
        pool.load_errors
    );

    let loci = contract_runtime_failure_loci(&pool);
    assert_eq!(
        loci,
        vec![
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "annassign.py",
                "line": 4,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {"kind": "var", "name": "key"}
                    ]
                },
                "file": "annassign.py",
                "line": 5,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "annassign.py",
                "line": 6,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "ys"},
                        {"kind": "var", "name": "i"}
                    ]
                },
                "file": "annassign.py",
                "line": 7,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-access",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {"kind": "var", "name": "obj"},
                        {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "annassign.py",
                "line": 8,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "attribute-write",
                "exceptionClass": "AttributeError",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:attribute",
                    "args": [
                        {
                            "kind": "ctor",
                            "name": "python:attribute",
                            "args": [
                                {"kind": "var", "name": "obj"},
                                {"kind": "const", "value": "inner", "sort": {"kind": "primitive", "name": "String"}}
                            ]
                        },
                        {"kind": "const", "value": "name", "sort": {"kind": "primitive", "name": "String"}}
                    ]
                },
                "file": "annassign.py",
                "line": 8,
                "col": 4
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-access",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "ys"},
                        {"kind": "var", "name": "i"}
                    ]
                },
                "file": "annassign.py",
                "line": 9,
                "col": 7
            }),
            json!({
                "effectKind": "panic-freedom",
                "callee": RUNTIME_FAILURE_SITE,
                "subkind": "subscript-write",
                "argTerm": {
                    "kind": "ctor",
                    "name": "python:subscript",
                    "args": [
                        {"kind": "var", "name": "xs"},
                        {
                            "kind": "ctor",
                            "name": "python:subscript",
                            "args": [
                                {"kind": "var", "name": "ys"},
                                {"kind": "var", "name": "i"}
                            ]
                        }
                    ]
                },
                "file": "annassign.py",
                "line": 9,
                "col": 4
            }),
        ],
        "mint must preserve python-source AnnAssign runtime-failure panicLoci rows"
    );

    let callsites = sugar_verifier::enumerate_callsites::run(&pool);
    let runtime_failure_sites: Vec<_> = callsites
        .iter()
        .filter(|cs| cs.panic_site && cs.callee.as_deref() == Some(RUNTIME_FAILURE_SITE))
        .collect();
    assert_eq!(
        runtime_failure_sites.len(),
        8,
        "verifier must surface exactly eight AnnAssign runtime-failure obligations; got {callsites:#?}"
    );
    assert!(
        runtime_failure_sites
            .iter()
            .all(|cs| cs.file.as_deref() == Some("annassign.py")),
        "all surfaced AnnAssign callsites must preserve annassign.py provenance: {runtime_failure_sites:#?}"
    );
    assert_eq!(
        runtime_failure_sites
            .iter()
            .map(|cs| (cs.line, cs.bridge_target_cid.is_none()))
            .collect::<Vec<_>>(),
        vec![
            (Some(4), true),
            (Some(5), true),
            (Some(6), true),
            (Some(7), true),
            (Some(8), true),
            (Some(8), true),
            (Some(9), true),
            (Some(9), true),
        ],
        "no bridges exist yet, so surfaced AnnAssign callsites must remain undecidable"
    );

    let _ = fs::remove_dir_all(&project);
}
